"""
Recipe Service — orchestration layer for the 9-step draft → publish flow.
"""
from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.recipe import (
    AutomationProfileCreate,
    BlueprintSnapshot,
    DomainCreate,
    DomainResponse,
    DomainUpdate,
    DraftCreate,
    DraftDetailResponse,
    DraftResponse,
    DraftUpdate,
    GatewayCreate,
    GatewayResponse,
    GatewayUpdate,
    GlobalDomainConfig,
    GlobalDomainResponse,
    IngressPolicyResponse,
    ListRecipesResponse,
    PublishedAccessBox,
    PublishedAutomationProfile,
    PublishedDomain,
    PublishedGateway,
    PublishedGlobalDomain,
    PublishedIngressPolicy,
    PublishedRecipeResponse,
    PublishedRoutingRule,
    PublishedWorkloadUnit,
    PublishResponse,
    RecipeListItem,
    RecipeMetadata,
    ValidationResult,
    WorkloadUnitCreate,
    WorkloadUnitResponse,
    WorkloadUnitUpdate,
    JumphostUnitInput,
)
from app.api.schemas.challenge import (
    ChallengeResponse,
    ChallengeWithRecipeResponse,
    RecipeSubset,
)
from app.models.challenge import Challenge
from app.models.recipe import Recipe, RecipeVersion, RecipeWorkloadUnit
from app.repositories.deployment_repository import DeploymentRepository
from app.repositories.recipe_repository import RecipeRepository

_repo = RecipeRepository()
_deployment_repo = DeploymentRepository()


# ─────────────────────────────── Domain size calculation ─────────────────────

def _calculate_domain_size(workload_unit_count: int) -> int:
    """
    Calculate the minimum CIDR subnet mask for a domain given the number of workload units.

    First 5 IPs and last 3 IPs are reserved (8 total).
    Returns the mask (e.g. 28 for /28).
    """
    total_needed = workload_unit_count + 8
    for mask in range(30, 7, -1):
        if (1 << (32 - mask)) >= total_needed:
            return mask
    return 8  # fallback for very large counts


async def _recalculate_domain_sizes(
    session: AsyncSession, recipe_id: uuid.UUID
) -> None:
    """Recalculate domain_size for all domains based on assigned workload units + jumphost."""
    recipe = await _repo.get_full_recipe(session, recipe_id)
    if not recipe:
        return

    domain_counts: dict[str, int] = {}
    for unit in recipe.workload_units:
        if unit.assigned_domain:
            domain_counts[unit.assigned_domain] = domain_counts.get(unit.assigned_domain, 0) + 1

    # Count jumphost if it has an assigned_domain
    if recipe.enable_jumphost and isinstance(recipe.jumphost_config, dict):
        jh_domain = recipe.jumphost_config.get("assigned_domain")
        if jh_domain:
            domain_counts[jh_domain] = domain_counts.get(jh_domain, 0) + 1

    for domain in recipe.network_domains:
        count = domain_counts.get(domain.name, 0)
        domain.domain_size = _calculate_domain_size(count) if count > 0 else None

    await session.flush()


# ─────────────────────────────── Step 1 — Create draft ───────────────────────

async def create_draft(
    session: AsyncSession,
    payload: DraftCreate,
    created_by: Optional[uuid.UUID] = None,
) -> DraftResponse:
    recipe_id = uuid.uuid4()
    await _repo.create_draft(
        session,
        recipe_id=recipe_id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        created_by=created_by,
    )
    return DraftResponse(recipe_id=recipe_id, status="draft_created")


async def list_drafts(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
) -> ListRecipesResponse:
    page_size = min(max(1, page_size), 100)
    page = max(1, page)
    rows, total = await _repo.list_drafts(session, page=page, page_size=page_size)
    items = [
        RecipeListItem(
            id=r.id,
            name=r.name,
            description=r.description,
            category=r.category,
            approval_status=getattr(r, "approval_status", "DRAFT"),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    has_more = (page * page_size) < total
    return ListRecipesResponse(
        items=items,
        next_page_token=str(page + 1) if has_more else None,
        total_size=total,
    )


# ─────────────────────────────── Step 2 — Global domain ──────────────────────

async def configure_global_domain(
    session: AsyncSession,
    recipe_id: uuid.UUID,
    payload: GlobalDomainConfig,
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    await _repo.upsert_network_profile(
        session,
        recipe_id=recipe_id,
        gateway_offset=payload.gw_offset,
    )
    await _repo.replace_dns_resolvers(
        session, recipe_id=recipe_id, addresses=payload.dns_resolvers
    )


# ─────────────────────────────── Step 3 — Domains ────────────────────────────

async def add_domain(
    session: AsyncSession,
    recipe_id: uuid.UUID,
    payload: DomainCreate,
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    await _repo.add_domain(
        session,
        recipe_id=recipe_id,
        name=payload.name,
        description=payload.description,
        enable_egress=payload.enable_egress,
    )


# ─────────────────────────────── Step 4 — Workload units ─────────────────────

async def add_workload_unit(
    session: AsyncSession,
    recipe_id: uuid.UUID,
    payload: WorkloadUnitCreate,
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    automation = (
        payload.automation_profile.model_dump() if payload.automation_profile else None
    )
    await _repo.add_workload_unit(
        session,
        recipe_id=recipe_id,
        name=payload.name,
        description=payload.description,
        allocation_index=payload.allocation_index,
        runtime_profile=payload.runtime_profile,
        resource_tier=payload.resource_tier,
        assigned_domain=payload.assigned_domain,
        access_method=payload.access_method,
        unit_control_active=payload.unit_control_active,
        automation=automation,
    )
    # Recalculate domain sizes after adding a unit
    await _recalculate_domain_sizes(session, recipe_id)


# ─────────────────────────────── Jumphost helper ─────────────────────────────

_JUMPHOST_DEFAULTS = {
    "enable": True,
    "allow_vnc": True,
    "resource_tier": "md",
    "assigned_domain": "internal",
    "domain": "internal",
    "runtime_profile": "oe:jumphost",
    "egress_ip": False,
    "allocation_index": 5,
}


def _jumphost_config(recipe: Recipe) -> dict:
    """Return stored jumphost_config or fall back to defaults."""
    stored = getattr(recipe, "jumphost_config", None)
    return stored if isinstance(stored, dict) else dict(_JUMPHOST_DEFAULTS)


async def set_jumphost_unit(
    session: AsyncSession,
    recipe_id: uuid.UUID,
    payload: JumphostUnitInput,
) -> dict:
    """Persist jumphost unit config on the recipe and return the stored dict."""
    recipe = await _load_full_or_404(session, recipe_id)
    config = payload.model_dump()
    # Map assigned_domain → domain for consistency
    config["domain"] = config.get("assigned_domain", config.get("domain", ""))
    recipe.jumphost_config = config
    recipe.enable_jumphost = config["enable"]
    await session.flush()
    # Recalculate domain sizes
    await _recalculate_domain_sizes(session, recipe_id)
    return config


# ─────────────────────────────── Step 5 — Gateways ───────────────────────────

async def add_gateway(
    session: AsyncSession,
    recipe_id: uuid.UUID,
    payload: GatewayCreate,
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    rules = [r.model_dump() for r in payload.ingress_policies]
    await _repo.add_gateway(
        session,
        recipe_id=recipe_id,
        gateway_key=payload.gateway_key,
        gateway_type=payload.gateway_type,
        runtime_profile=payload.runtime_profile,
        resource_tier=payload.resource_tier,
        is_active=payload.is_active,
        secure_shell=payload.secure_shell,
        egress_ip=payload.egress_ip,
        ingress_policies=rules,
    )


# ─────────────────────────────── Step 8 — Validate ───────────────────────────

async def validate_draft(
    session: AsyncSession, recipe_id: uuid.UUID
) -> ValidationResult:
    recipe = await _load_full_or_404(session, recipe_id)
    errors = _run_validation_checks(recipe)
    return ValidationResult(is_valid=len(errors) == 0, errors=errors)


# ─────────────────────────────── Step 9 — Publish ────────────────────────────

async def publish_draft(
    session: AsyncSession, recipe_id: uuid.UUID
) -> PublishedRecipeResponse:
    draft = await _repo.get_draft_by_id(session, recipe_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipe '{recipe_id}' not found",
        )
    if draft.approval_status != "APPROVED":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Recipe not approved",
                "approval_status": draft.approval_status,
                "hint": "Call POST /drafts/{id}/submit first.",
            },
        )

    recipe = await _load_full_or_404(session, recipe_id)
    errors = _run_validation_checks(recipe)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Draft failed validation", "errors": errors},
        )

    blueprint = _serialize_blueprint(recipe)
    checksum = hashlib.sha256(blueprint.model_dump_json(indent=None).encode()).hexdigest()

    next_version = await _repo.get_next_version_number(session, recipe_id)
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    version = await _repo.create_version(
        session,
        recipe_id=recipe_id,
        version_number=next_version,
        checksum=checksum,
    )

    published = _build_published_response(
        recipe=recipe,
        version_id=version.id,
        version_number=next_version,
        checksum=checksum,
        published_at=published_at,
    )
    await _repo.create_snapshot(
        session,
        version_id=version.id,
        snapshot_json=published.model_dump(mode="json"),
    )
    await _repo.increment_recipe_version(
        session, recipe_id=recipe_id, new_version=next_version
    )

    return published


# ─────────────────────────────── Validation logic ────────────────────────────

def _run_validation_checks(recipe: Recipe) -> list[str]:
    errors: list[str] = []

    domain_names = {d.name for d in recipe.network_domains}
    unit_names = {u.name for u in recipe.workload_units}

    # 1. Unit → domain mapping
    for unit in recipe.workload_units:
        if unit.assigned_domain and unit.assigned_domain not in domain_names:
            errors.append(
                f"Unit '{unit.name}': assigned_domain '{unit.assigned_domain}' does not exist"
            )

    # 2. No duplicate allocation_index
    indices = [
        u.allocation_index
        for u in recipe.workload_units
        if u.allocation_index is not None
    ]
    if len(indices) != len(set(indices)):
        errors.append("Duplicate allocation_index values detected in workload units")

    # 3. Routing rules reference existing domains
    for rule in recipe.domain_routing_rules:
        if rule.source_domain and rule.source_domain not in domain_names:
            errors.append(
                f"Routing rule: source_domain '{rule.source_domain}' does not exist"
            )
        if rule.destination_domain and rule.destination_domain not in domain_names:
            errors.append(
                f"Routing rule: destination_domain '{rule.destination_domain}' does not exist"
            )

    # 4. No circular routing
    allow_graph: dict[str, set[str]] = {}
    for rule in recipe.domain_routing_rules:
        if rule.routing_policy == "allow" and rule.source_domain and rule.destination_domain:
            allow_graph.setdefault(rule.source_domain, set()).add(rule.destination_domain)
    if _has_cycle(allow_graph):
        errors.append("Circular routing detected in domain routing rules")

    # 5. Gateway ingress policies → wl_unit exists
    for gw in recipe.access_gateways:
        for rule in gw.exposure_rules:
            if rule.wl_unit and rule.wl_unit not in unit_names:
                errors.append(
                    f"Gateway '{gw.gateway_key}' ingress policy references "
                    f"non-existent unit '{rule.wl_unit}'"
                )

    return errors


def _has_cycle(graph: dict[str, set[str]]) -> bool:
    """Iterative DFS cycle detection."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in graph}

    def dfs(start: str) -> bool:
        stack = [(start, iter(graph.get(start, [])))]
        color[start] = GRAY
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
                if color.get(child, WHITE) == GRAY:
                    return True
                if color.get(child, WHITE) == WHITE:
                    color[child] = GRAY
                    stack.append((child, iter(graph.get(child, []))))
            except StopIteration:
                color[node] = BLACK
                stack.pop()
        return False

    for node in list(graph):
        if color.get(node, WHITE) == WHITE and dfs(node):
            return True
    return False


# ─────────────────────────────── Blueprint serialiser ────────────────────────

def _serialize_blueprint(recipe: Recipe) -> BlueprintSnapshot:
    global_domain = None
    if recipe.network_profiles:
        p = recipe.network_profiles[0]
        global_domain = {
            "gw_offset": p.gateway_offset,
            "dns": [r.resolver_address for r in recipe.dns_resolvers],
        }

    return BlueprintSnapshot(
        recipe_id=str(recipe.id),
        name=recipe.name,
        description=recipe.description,
        category=recipe.category,
        enable_jumphost=recipe.enable_jumphost,
        global_domain=global_domain,
        network_domains=[
            {
                "name": d.name,
                "desc": d.description,
                "enable_egress": d.enable_egress,
                "domain_size": d.domain_size,
            }
            for d in recipe.network_domains
        ],
        domain_routing_rules=[
            {
                "source_domain": r.source_domain,
                "destination_domain": r.destination_domain,
                "routing_policy": r.routing_policy,
            }
            for r in recipe.domain_routing_rules
        ],
        workload_units=[
            {
                "name": u.name,
                "description": u.description,
                "allocation_index": u.allocation_index,
                "runtime_profile": u.runtime_profile,
                "resource_tier": u.resource_tier,
                "assigned_domain": u.assigned_domain,
                "access_method": u.access_method,
                "unit_control_active": u.unit_control_active,
                "automations": (
                    {
                        "bootstrap_automation": u.automation_profile.bootstrap_automation,
                        "preflight_automation": u.automation_profile.preflight_automation,
                        "heartbeat_automation": u.automation_profile.heartbeat_automation,
                    }
                    if u.automation_profile
                    else None
                ),
            }
            for u in recipe.workload_units
        ],
        access_gateways=[
            {
                "gateway_key": g.gateway_key,
                "gateway_type": g.gateway_type,
                "runtime_profile": g.runtime_profile,
                "resource_tier": g.resource_tier,
                "is_active": g.is_active,
                "secure_shell": g.secure_shell,
                "egress_ip": g.egress_ip,
                "ingress_policies": [
                    {
                        "wl_unit": r.wl_unit,
                        "int_port": r.int_port,
                        "proto": r.proto,
                        "name": r.rule_name,
                        "desc": r.rule_desc,
                        "ext_port": r.ext_port,
                    }
                    for r in g.exposure_rules
                ],
            }
            for g in recipe.access_gateways
        ],
        access_box=(
            _jumphost_config(recipe)
            if getattr(recipe, "enable_jumphost", True)
            else None
        ),
    )


# ─────────────────────────────── Published response builder ──────────────────

def _build_published_response(
    recipe: Recipe,
    version_id: uuid.UUID,
    version_number: int,
    checksum: str,
    published_at: str,
) -> PublishedRecipeResponse:
    """Build the immutable published recipe snapshot."""
    unit_name_to_id: dict[str, uuid.UUID] = {
        u.name: u.id for u in recipe.workload_units
    }

    # ── Global domain ─────────────────────────────────────────────────────────
    global_domain = None
    if recipe.network_profiles:
        p = recipe.network_profiles[0]
        global_domain = PublishedGlobalDomain(
            dns=[r.resolver_address for r in recipe.dns_resolvers],
            gw_offset=p.gateway_offset,
        )

    # ── Domains ──────────────────────────────────────────────────────────────
    domains = [
        PublishedDomain(
            id=d.id,
            name=d.name,
            desc=d.description,
            enable_egress=d.enable_egress,
            domain_size=d.domain_size,
        )
        for d in recipe.network_domains
    ]

    # ── Workload units ────────────────────────────────────────────────────────
    workload_units = []
    for u in recipe.workload_units:
        ap = None
        if u.automation_profile:
            ap = PublishedAutomationProfile(
                bootstrap_automation=u.automation_profile.bootstrap_automation,
                preflight_automation=u.automation_profile.preflight_automation,
                heartbeat_automation=u.automation_profile.heartbeat_automation,
            )
        workload_units.append(PublishedWorkloadUnit(
            id=u.id,
            name=u.name,
            description=u.description,
            allocation_index=u.allocation_index,
            runtime_profile=u.runtime_profile,
            resource_tier=u.resource_tier,
            assigned_domain=u.assigned_domain,
            access_method=u.access_method,
            unit_control_active=u.unit_control_active,
            automations=ap,
        ))

    # ── Gateways (ingress policies use unit_id) ───────────────────────────────
    gateways = []
    for g in recipe.access_gateways:
        ingress_policies = [
            PublishedIngressPolicy(
                unit_id=unit_name_to_id[r.wl_unit],
                name=r.rule_name,
                proto=r.proto,
                desc=r.rule_desc,
                ext_port=r.ext_port,
                int_port=r.int_port,
            )
            for r in g.exposure_rules
            if r.wl_unit and r.wl_unit in unit_name_to_id
            and r.int_port and r.proto
        ]
        gateways.append(PublishedGateway(
            id=g.id,
            secure_shell=g.secure_shell,
            runtime_profile=g.runtime_profile,
            resource_tier=g.resource_tier,
            egress_ip=g.egress_ip,
            ingress_policies=ingress_policies,
        ))

    # ── Access box (jumphost) ─────────────────────────────────────────────────
    access_box = None
    if getattr(recipe, "enable_jumphost", True):
        cfg = _jumphost_config(recipe)
        access_box = PublishedAccessBox(
            enable=cfg.get("enable", True),
            domain=cfg.get("domain") or cfg.get("assigned_domain", ""),
            runtime_profile=cfg.get("runtime_profile", ""),
            resource_tier=cfg.get("resource_tier", ""),
            allocation_index=cfg.get("allocation_index", 5),
            egress_ip=cfg.get("egress_ip", False),
            allow_vnc=cfg.get("allow_vnc", True),
        )

    return PublishedRecipeResponse(
        recipe_version_id=version_id,
        version_number=version_number,
        published_at=published_at,
        checksum=checksum,
        metadata=RecipeMetadata(
            name=recipe.name,
            description=recipe.description,
            category=recipe.category,
            enable_jumphost=recipe.enable_jumphost,
        ),
        global_domain=global_domain,
        domains=domains,
        workload_units=workload_units,
        gateways=gateways,
        access_box=access_box,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  GET / UPDATE endpoints — service layer
# ═══════════════════════════════════════════════════════════════════════════════

def _gateway_to_response(gw) -> GatewayResponse:
    return GatewayResponse(
        id=gw.id,
        recipe_id=gw.recipe_id,
        gateway_key=gw.gateway_key,
        gateway_type=gw.gateway_type,
        runtime_profile=gw.runtime_profile,
        resource_tier=gw.resource_tier,
        is_active=gw.is_active,
        secure_shell=gw.secure_shell,
        egress_ip=gw.egress_ip,
        ingress_policies=[
            IngressPolicyResponse.from_orm_rule(r)
            for r in (gw.exposure_rules or [])
        ],
    )


def _unit_to_response(u) -> WorkloadUnitResponse:
    ap = None
    if u.automation_profile:
        ap = AutomationProfileCreate.model_validate(u.automation_profile)
    return WorkloadUnitResponse(
        id=u.id,
        recipe_id=u.recipe_id,
        name=u.name,
        description=u.description,
        allocation_index=u.allocation_index,
        runtime_profile=u.runtime_profile,
        resource_tier=u.resource_tier,
        assigned_domain=u.assigned_domain,
        access_method=u.access_method,
        unit_control_active=u.unit_control_active,
        automation_profile=ap,
    )


# ── Exercises loader ──────────────────────────────────────────────────────────

async def _load_exercises_for_recipe(
    session: AsyncSession, recipe_id: uuid.UUID, recipe: Recipe
) -> list[ChallengeWithRecipeResponse]:
    version_result = await session.execute(
        select(RecipeVersion).where(RecipeVersion.recipe_id == recipe_id)
    )
    versions = version_result.scalars().all()
    if not versions:
        return []
    version_id_to_num = {v.id: v.version_number for v in versions}

    ei_result = await session.execute(
        select(Challenge)
        .options(
            selectinload(Challenge.validation_targets),
            selectinload(Challenge.hints),
            selectinload(Challenge.attachments),
            selectinload(Challenge.objectives),
            selectinload(Challenge.dependencies),
        )
        .where(
            Challenge.recipe_version_id.in_(list(version_id_to_num.keys())),
            Challenge.deleted_at.is_(None),
        )
    )
    instances = ei_result.scalars().all()

    result = []
    for ei in instances:
        recipe_subset = RecipeSubset(
            recipe_id=recipe.id,
            name=recipe.name,
            category=recipe.category,
            version_number=version_id_to_num.get(ei.recipe_version_id, 0),
            recipe_version_id=ei.recipe_version_id,
        )
        result.append(
            ChallengeWithRecipeResponse(
                **ChallengeResponse.model_validate(ei).model_dump(),
                recipe=recipe_subset,
            )
        )
    return result


# ── Draft ─────────────────────────────────────────────────────────────────────

async def get_draft_detail(
    session: AsyncSession, recipe_id: uuid.UUID
) -> DraftDetailResponse:
    draft = await _repo.get_draft_by_id(session, recipe_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipe '{recipe_id}' not found",
        )
    recipe = await _load_full_or_404(session, recipe_id)

    global_domain = None
    if recipe.network_profiles:
        p = recipe.network_profiles[0]
        dns = [r.resolver_address for r in recipe.dns_resolvers]
        global_domain = GlobalDomainResponse(
            id=p.id,
            recipe_id=p.recipe_id,
            gw_offset=p.gateway_offset,
            dns=dns,
        )

    exercises = await _load_exercises_for_recipe(session, recipe_id, recipe)

    return DraftDetailResponse(
        recipe_id=draft.id,
        name=draft.name,
        description=draft.description,
        category=draft.category,
        enable_jumphost=recipe.enable_jumphost,
        approval_status=draft.approval_status,
        global_domain=global_domain,
        domains=[DomainResponse.from_orm_domain(d) for d in recipe.network_domains],
        workload_units=[_unit_to_response(u) for u in recipe.workload_units],
        exercises=exercises,
        gateways=[_gateway_to_response(gw) for gw in recipe.access_gateways],
    )


async def update_draft(
    session: AsyncSession, recipe_id: uuid.UUID, payload: DraftUpdate
) -> DraftDetailResponse:
    await _assert_recipe_exists(session, recipe_id)
    updates = payload.model_dump(exclude_unset=True)
    await _repo.update_draft_metadata(session, recipe_id=recipe_id, updates=updates)
    return await get_draft_detail(session, recipe_id)


# ── Global domain ─────────────────────────────────────────────────────────────

async def get_global_domain(
    session: AsyncSession, recipe_id: uuid.UUID
) -> GlobalDomainResponse:
    await _assert_recipe_exists(session, recipe_id)
    recipe = await _load_full_or_404(session, recipe_id)
    if not recipe.network_profiles:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Global domain not configured for this recipe")
    p = recipe.network_profiles[0]
    dns = [r.resolver_address for r in recipe.dns_resolvers]
    return GlobalDomainResponse(
        id=p.id, recipe_id=p.recipe_id,
        gw_offset=p.gateway_offset,
        dns=dns,
    )


# ── Domains ───────────────────────────────────────────────────────────────────

async def list_domains(
    session: AsyncSession, recipe_id: uuid.UUID
) -> list[DomainResponse]:
    recipe = await _load_full_or_404(session, recipe_id)
    return [DomainResponse.from_orm_domain(d) for d in recipe.network_domains]


async def get_domain(
    session: AsyncSession, recipe_id: uuid.UUID, domain_id: uuid.UUID
) -> DomainResponse:
    await _assert_recipe_exists(session, recipe_id)
    domain = await _repo.get_domain_by_id(session, domain_id)
    if domain is None or domain.recipe_id != recipe_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")
    return DomainResponse.from_orm_domain(domain)


async def update_domain(
    session: AsyncSession, recipe_id: uuid.UUID, domain_id: uuid.UUID, payload: DomainUpdate
) -> DomainResponse:
    await _assert_recipe_exists(session, recipe_id)
    domain = await _repo.get_domain_by_id(session, domain_id)
    if domain is None or domain.recipe_id != recipe_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")
    updates = payload.model_dump(exclude_unset=True)
    # Map schema field "description" from DomainUpdate if present
    domain = await _repo.update_domain(session, domain=domain, updates=updates)
    return DomainResponse.from_orm_domain(domain)


async def delete_domain(
    session: AsyncSession, recipe_id: uuid.UUID, domain_id: uuid.UUID
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    deleted = await _repo.delete_domain_by_id(session, recipe_id=recipe_id, domain_id=domain_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")
    await _recalculate_domain_sizes(session, recipe_id)


# ── Workload units ────────────────────────────────────────────────────────────

async def list_units(
    session: AsyncSession, recipe_id: uuid.UUID
) -> list[WorkloadUnitResponse]:
    recipe = await _load_full_or_404(session, recipe_id)
    return [_unit_to_response(u) for u in recipe.workload_units]


async def get_unit(
    session: AsyncSession, recipe_id: uuid.UUID, unit_id: uuid.UUID
) -> WorkloadUnitResponse:
    await _assert_recipe_exists(session, recipe_id)
    unit = await _repo.get_unit_by_id(session, unit_id)
    if unit is None or unit.recipe_id != recipe_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workload unit not found")
    return _unit_to_response(unit)


async def update_unit(
    session: AsyncSession, recipe_id: uuid.UUID, unit_id: uuid.UUID, payload: WorkloadUnitUpdate
) -> WorkloadUnitResponse:
    await _assert_recipe_exists(session, recipe_id)
    unit = await _repo.get_unit_by_id(session, unit_id)
    if unit is None or unit.recipe_id != recipe_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workload unit not found")
    updates = payload.model_dump(exclude_unset=True)
    automation = updates.pop("automation_profile", None)
    unit = await _repo.update_unit(session, unit=unit, updates=updates, automation=automation)
    await _recalculate_domain_sizes(session, recipe_id)
    return _unit_to_response(unit)


async def delete_unit(
    session: AsyncSession, recipe_id: uuid.UUID, unit_id: uuid.UUID
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    deleted = await _repo.delete_unit_by_id(session, recipe_id=recipe_id, unit_id=unit_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workload unit not found")
    await _recalculate_domain_sizes(session, recipe_id)


# ── Gateways ──────────────────────────────────────────────────────────────────

async def list_gateways(
    session: AsyncSession, recipe_id: uuid.UUID
) -> list[GatewayResponse]:
    recipe = await _load_full_or_404(session, recipe_id)
    return [_gateway_to_response(gw) for gw in recipe.access_gateways]


async def get_gateway(
    session: AsyncSession, recipe_id: uuid.UUID, gateway_id: uuid.UUID
) -> GatewayResponse:
    await _assert_recipe_exists(session, recipe_id)
    gw = await _repo.get_gateway_by_id(session, gateway_id)
    if gw is None or gw.recipe_id != recipe_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found")
    return _gateway_to_response(gw)


async def update_gateway(
    session: AsyncSession, recipe_id: uuid.UUID, gateway_id: uuid.UUID, payload: GatewayUpdate
) -> GatewayResponse:
    await _assert_recipe_exists(session, recipe_id)
    gw = await _repo.get_gateway_by_id(session, gateway_id)
    if gw is None or gw.recipe_id != recipe_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found")
    updates = payload.model_dump(exclude_unset=True)
    raw_rules = updates.pop("ingress_policies", None)
    ingress_policies = [r.model_dump() for r in raw_rules] if raw_rules is not None else None
    gw = await _repo.update_gateway(
        session, gateway=gw, updates=updates, ingress_policies=ingress_policies
    )
    return _gateway_to_response(gw)


async def delete_gateway(
    session: AsyncSession, recipe_id: uuid.UUID, gateway_id: uuid.UUID
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    deleted = await _repo.delete_gateway_by_id(
        session, recipe_id=recipe_id, gateway_id=gateway_id
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found")


# ─────────────────────────────── Helpers ─────────────────────────────────────

async def delete_draft(session: AsyncSession, recipe_id: uuid.UUID) -> None:
    draft = await _repo.get_draft_by_id(session, recipe_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found",
        )
    version_ids = await _repo.get_version_ids_by_draft_id(session, recipe_id)
    if version_ids:
        count = await _deployment_repo.count_by_recipe_version_ids(session, version_ids)
        if count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "Draft has published versions in use by deployments",
                    "message": "Delete or archive all deployments using this recipe before deleting the draft.",
                },
            )
    await _repo.delete_draft(session, recipe_id)


async def _assert_recipe_exists(session: AsyncSession, recipe_id: uuid.UUID) -> None:
    recipe = await _repo.get_full_recipe(session, recipe_id)
    if recipe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipe '{recipe_id}' not found",
        )


async def _load_full_or_404(session: AsyncSession, recipe_id: uuid.UUID) -> Recipe:
    recipe = await _repo.get_full_recipe(session, recipe_id)
    if recipe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipe '{recipe_id}' not found",
        )
    return recipe
