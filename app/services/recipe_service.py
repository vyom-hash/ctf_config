"""
Recipe Service — orchestration layer for the 9-step draft → publish flow.

Responsibilities
────────────────
• Translate HTTP inputs into repository calls.
• Enforce business rules (validate draft, serialize blueprint, checksum).
• Own the transaction boundary (session is committed by the FastAPI dependency
  after the service returns; errors trigger automatic rollback).
"""
from __future__ import annotations

import hashlib
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
    ExposureRuleResponse,
    GatewayCreate,
    GatewayResponse,
    GatewayUpdate,
    ListRecipesResponse,
    NetworkProfileConfig,
    NetworkProfileResponse,
    PublishedAutomationProfile,
    PublishedDomain,
    PublishedExposureRule,
    PublishedGateway,
    PublishedJumphostUnit,
    PublishedNetworkProfile,
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
)
from app.api.schemas.exercise_instance import (
    ExerciseInstanceResponse,
    ExerciseWithRecipeResponse,
    RecipeSubset,
)
from app.models.exercise_instance import ExerciseInstance
from app.models.recipe import Recipe, RecipeVersion
from app.repositories.deployment_repository import DeploymentRepository
from app.repositories.recipe_repository import RecipeRepository

_repo = RecipeRepository()
_deployment_repo = DeploymentRepository()


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
    """List recipe drafts with pagination. Returns Google-style list envelope."""
    page_size = min(max(1, page_size), 100)
    page = max(1, page)
    rows, total = await _repo.list_drafts(
        session, page=page, page_size=page_size
    )
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
    next_page_token = str(page + 1) if has_more else None
    return ListRecipesResponse(
        items=items,
        next_page_token=next_page_token,
        total_size=total,
    )


# ─────────────────────────────── Step 2 — Network profile ────────────────────

async def configure_network_profile(
    session: AsyncSession,
    recipe_id: uuid.UUID,
    payload: NetworkProfileConfig,
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    await _repo.upsert_network_profile(
        session,
        recipe_id=recipe_id,
        segmentation_strategy=payload.segmentation_strategy,
        default_subnet_mask=payload.default_subnet_mask,
        gateway_offset=payload.gateway_offset,
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
        domain_key=payload.domain_key,
        description=payload.description,
        public_ingress_enabled=payload.public_ingress_enabled,
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
        unit_key=payload.unit_key,
        functional_role=payload.functional_role,
        network_position_index=payload.network_position_index,
        runtime_profile=payload.runtime_profile,
        resource_tier=payload.resource_tier,
        assigned_domain=payload.assigned_domain,
        connectivity_profile=payload.connectivity_profile,
        agent_enabled=payload.agent_enabled,
        automation=automation,
    )


# ─────────────────────────────── Step 5 — Gateways ───────────────────────────

async def add_gateway(
    session: AsyncSession,
    recipe_id: uuid.UUID,
    payload: GatewayCreate,
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    rules = [r.model_dump() for r in payload.exposure_rules]
    await _repo.add_gateway(
        session,
        recipe_id=recipe_id,
        gateway_key=payload.gateway_key,
        gateway_type=payload.gateway_type,
        runtime_profile=payload.runtime_profile,
        resource_tier=payload.resource_tier,
        is_active=payload.is_active,
        exposure_rules=rules,
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
    # ── Approval gate ────────────────────────────────────────────────────────
    # Draft must have been explicitly submitted and approved before it can be
    # published.  When AUTO_APPROVE_RECIPES=True the submit step does this
    # automatically; otherwise a human reviewer must approve first.
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

    # Re-validate before publish
    errors = _run_validation_checks(recipe)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Draft failed validation", "errors": errors},
        )

    # SHA-256 checksum derived from the canonical BlueprintSnapshot JSON
    # (kept stable across format changes to the published response shape)
    blueprint = _serialize_blueprint(recipe)
    checksum = hashlib.sha256(blueprint.model_dump_json(indent=None).encode()).hexdigest()

    next_version = await _repo.get_next_version_number(session, recipe_id)
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Persist version row
    version = await _repo.create_version(
        session,
        recipe_id=recipe_id,
        version_number=next_version,
        checksum=checksum,
    )

    # Build the hardened published response and store it as the snapshot
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

    domain_keys = {d.domain_key for d in recipe.network_domains}
    unit_keys = {u.unit_key for u in recipe.workload_units}

    # 1. Unit → domain mapping
    for unit in recipe.workload_units:
        if unit.assigned_domain and unit.assigned_domain not in domain_keys:
            errors.append(
                f"Unit '{unit.unit_key}': assigned_domain '{unit.assigned_domain}' does not exist"
            )

    # 2. No duplicate network_position_index
    indices = [
        u.network_position_index
        for u in recipe.workload_units
        if u.network_position_index is not None
    ]
    if len(indices) != len(set(indices)):
        errors.append("Duplicate network_position_index values detected in workload units")

    # 3. Routing rules reference existing domains
    for rule in recipe.domain_routing_rules:
        if rule.source_domain and rule.source_domain not in domain_keys:
            errors.append(
                f"Routing rule: source_domain '{rule.source_domain}' does not exist"
            )
        if rule.destination_domain and rule.destination_domain not in domain_keys:
            errors.append(
                f"Routing rule: destination_domain '{rule.destination_domain}' does not exist"
            )

    # 4. No circular routing (DFS cycle detection on allow-policy edges)
    allow_graph: dict[str, set[str]] = {}
    for rule in recipe.domain_routing_rules:
        if rule.routing_policy == "allow" and rule.source_domain and rule.destination_domain:
            allow_graph.setdefault(rule.source_domain, set()).add(rule.destination_domain)
    if _has_cycle(allow_graph):
        errors.append("Circular routing detected in domain routing rules")

    # 5. Gateway exposure rules → unit_key exists (no assigned gateway / attached_domain)
    for gw in recipe.access_gateways:
        for rule in gw.exposure_rules:
            if rule.unit_key and rule.unit_key not in unit_keys:
                errors.append(
                    f"Gateway '{gw.gateway_key}' exposure rule references "
                    f"non-existent unit_key '{rule.unit_key}'"
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
    net_profile = None
    if recipe.network_profiles:
        p = recipe.network_profiles[0]
        net_profile = {
            "segmentation_strategy": p.segmentation_strategy,
            "default_subnet_mask": p.default_subnet_mask,
            "gateway_offset": p.gateway_offset,
        }

    return BlueprintSnapshot(
        recipe_id=str(recipe.id),
        name=recipe.name,
        description=recipe.description,
        category=recipe.category,
        enable_jumphost=recipe.enable_jumphost,
        network_profile=net_profile,
        dns_resolvers=[r.resolver_address for r in recipe.dns_resolvers],
        network_domains=[
            {
                "domain_key": d.domain_key,
                "description": d.description,
                "public_ingress_enabled": d.public_ingress_enabled,
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
                "unit_key": u.unit_key,
                "functional_role": u.functional_role,
                "network_position_index": u.network_position_index,
                "runtime_profile": u.runtime_profile,
                "resource_tier": u.resource_tier,
                "assigned_domain": u.assigned_domain,
                "connectivity_profile": u.connectivity_profile,
                "agent_enabled": u.agent_enabled,
                "automation_profile": (
                    {
                        "bootstrap_reference": u.automation_profile.bootstrap_reference,
                        "initialization_reference": u.automation_profile.initialization_reference,
                        "health_check_reference": u.automation_profile.health_check_reference,
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
                "exposure_rules": [
                    {
                        "unit_key": r.unit_key,
                        "internal_port": r.internal_port,
                        "transport_protocol": r.transport_protocol,
                    }
                    for r in g.exposure_rules
                ],
            }
            for g in recipe.access_gateways
        ],
        jumphost_unit=(
            {
                "enabled": True,
                "assigned_domain": "internal",
                "runtime_profile": "oe:jumphost",
                "enable_vnc": True,
                "network_position_index": 5,
                "resource_tier": "md",
                "enable_floating_ip": False,
            }
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
    """
    Build the production-grade immutable published recipe response.

    Key differences from the draft view:
    • routing_rules are embedded inside network_profile
    • Exposure rules reference unit_id (UUID), not the mutable unit_key string
    • Null optional fields are stripped from workload units
    • connectivity_profile is excluded (runtime concern, not recipe config)
    """
    unit_key_to_id: dict[str, uuid.UUID] = {
        u.unit_key: u.id for u in recipe.workload_units
    }

    # ── Network profile + routing rules ──────────────────────────────────────
    net_profile = None
    if recipe.network_profiles:
        p = recipe.network_profiles[0]
        routing_rules = [
            PublishedRoutingRule(
                source_domain=r.source_domain,
                destination_domain=r.destination_domain,
                routing_policy=r.routing_policy,
            )
            for r in recipe.domain_routing_rules
            if r.source_domain and r.destination_domain and r.routing_policy
        ]
        net_profile = PublishedNetworkProfile(
            segmentation_strategy=p.segmentation_strategy,
            default_subnet_mask=p.default_subnet_mask,
            gateway_offset=p.gateway_offset,
            dns_resolvers=[r.resolver_address for r in recipe.dns_resolvers],
            routing_rules=routing_rules,
        )

    # ── Domains ──────────────────────────────────────────────────────────────
    domains = [
        PublishedDomain(
            id=d.id,
            domain_key=d.domain_key,
            description=d.description,
            public_ingress_enabled=d.public_ingress_enabled,
        )
        for d in recipe.network_domains
    ]

    # ── Workload units (no connectivity_profile, nulls stripped) ─────────────
    workload_units = []
    for u in recipe.workload_units:
        ap = None
        if u.automation_profile:
            ap = PublishedAutomationProfile(
                bootstrap_reference=u.automation_profile.bootstrap_reference,
                initialization_reference=u.automation_profile.initialization_reference,
                health_check_reference=u.automation_profile.health_check_reference,
            )
        workload_units.append(PublishedWorkloadUnit(
            id=u.id,
            unit_key=u.unit_key,
            functional_role=u.functional_role,
            network_position_index=u.network_position_index,
            runtime_profile=u.runtime_profile,
            resource_tier=u.resource_tier,
            assigned_domain=u.assigned_domain,
            agent_enabled=u.agent_enabled,
            automation_profile=ap,
        ))

    # ── Gateways (exposure rules use unit_id) ────────────────────────────────
    gateways = []
    for g in recipe.access_gateways:
        exposure_rules = [
            PublishedExposureRule(
                unit_id=unit_key_to_id[r.unit_key],
                internal_port=r.internal_port,
                transport_protocol=r.transport_protocol,
            )
            for r in g.exposure_rules
            if r.unit_key and r.unit_key in unit_key_to_id
            and r.internal_port and r.transport_protocol
        ]
        gateways.append(PublishedGateway(
            id=g.id,
            gateway_key=g.gateway_key,
            gateway_type=g.gateway_type or "",
            runtime_profile=g.runtime_profile,
            resource_tier=g.resource_tier,
            exposure_rules=exposure_rules,
        ))

    # ── Scoring and challenges are not part of recipe; omitted from snapshot ───

    jumphost_unit = None
    if getattr(recipe, "enable_jumphost", True):
        jumphost_unit = PublishedJumphostUnit(
            enabled=True,
            assigned_domain="internal",
            runtime_profile="oe:jumphost",
            enable_vnc=True,
            network_position_index=5,
            resource_tier="md",
            enable_floating_ip=False,
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
        network_profile=net_profile,
        domains=domains,
        workload_units=workload_units,
        gateways=gateways,
        jumphost_unit=jumphost_unit,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  GET / UPDATE endpoints — service layer
# ═══════════════════════════════════════════════════════════════════════════════

# ── helpers ───────────────────────────────────────────────────────────────────

def _gateway_to_response(gw) -> GatewayResponse:
    return GatewayResponse(
        id=gw.id,
        recipe_id=gw.recipe_id,
        gateway_key=gw.gateway_key,
        gateway_type=gw.gateway_type,
        runtime_profile=gw.runtime_profile,
        resource_tier=gw.resource_tier,
        is_active=gw.is_active,
        exposure_rules=[ExposureRuleResponse.model_validate(r) for r in (gw.exposure_rules or [])],
    )


def _unit_to_response(u) -> WorkloadUnitResponse:
    ap = None
    if u.automation_profile:
        ap = AutomationProfileCreate.model_validate(u.automation_profile)
    return WorkloadUnitResponse(
        id=u.id,
        recipe_id=u.recipe_id,
        unit_key=u.unit_key,
        functional_role=u.functional_role,
        network_position_index=u.network_position_index,
        runtime_profile=u.runtime_profile,
        resource_tier=u.resource_tier,
        assigned_domain=u.assigned_domain,
        connectivity_profile=u.connectivity_profile,
        agent_enabled=u.agent_enabled,
        automation_profile=ap,
    )


# ── Exercises loader (superset data for exercises field) ──────────────────────

async def _load_exercises_for_recipe(
    session: AsyncSession, recipe_id: uuid.UUID, recipe: Recipe
) -> list[ExerciseWithRecipeResponse]:
    """Load all active ExerciseInstances for any version of a recipe, with recipe subset embedded."""
    version_result = await session.execute(
        select(RecipeVersion).where(RecipeVersion.recipe_id == recipe_id)
    )
    versions = version_result.scalars().all()
    if not versions:
        return []
    version_id_to_num = {v.id: v.version_number for v in versions}

    ei_result = await session.execute(
        select(ExerciseInstance)
        .options(
            selectinload(ExerciseInstance.validation_targets),
            selectinload(ExerciseInstance.guidance_steps),
            selectinload(ExerciseInstance.attachments),
            selectinload(ExerciseInstance.point_checkpoints),
            selectinload(ExerciseInstance.dependencies),
        )
        .where(
            ExerciseInstance.recipe_version_id.in_(list(version_id_to_num.keys())),
            ExerciseInstance.deleted_at.is_(None),
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
            ExerciseWithRecipeResponse(
                **ExerciseInstanceResponse.model_validate(ei).model_dump(),
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

    net_profile = None
    if recipe.network_profiles:
        p = recipe.network_profiles[0]
        dns = [r.resolver_address for r in recipe.dns_resolvers]
        net_profile = NetworkProfileResponse(
            id=p.id, recipe_id=p.recipe_id,
            segmentation_strategy=p.segmentation_strategy,
            default_subnet_mask=p.default_subnet_mask,
            gateway_offset=p.gateway_offset,
            dns_resolvers=dns,
        )

    exercises = await _load_exercises_for_recipe(session, recipe_id, recipe)

    return DraftDetailResponse(
        recipe_id=draft.id,
        name=draft.name,
        description=draft.description,
        category=draft.category,
        enable_jumphost=recipe.enable_jumphost,
        approval_status=draft.approval_status,
        network_profile=net_profile,
        domains=[DomainResponse.model_validate(d) for d in recipe.network_domains],
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


# ── Network profile ───────────────────────────────────────────────────────────

async def get_network_profile(
    session: AsyncSession, recipe_id: uuid.UUID
) -> NetworkProfileResponse:
    await _assert_recipe_exists(session, recipe_id)
    recipe = await _load_full_or_404(session, recipe_id)
    if not recipe.network_profiles:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Network profile not configured for this draft")
    p = recipe.network_profiles[0]
    dns = [r.resolver_address for r in recipe.dns_resolvers]
    return NetworkProfileResponse(
        id=p.id, recipe_id=p.recipe_id,
        segmentation_strategy=p.segmentation_strategy,
        default_subnet_mask=p.default_subnet_mask,
        gateway_offset=p.gateway_offset,
        dns_resolvers=dns,
    )


# ── Domains ───────────────────────────────────────────────────────────────────

async def list_domains(
    session: AsyncSession, recipe_id: uuid.UUID
) -> list[DomainResponse]:
    recipe = await _load_full_or_404(session, recipe_id)
    return [DomainResponse.model_validate(d) for d in recipe.network_domains]


async def get_domain(
    session: AsyncSession, recipe_id: uuid.UUID, domain_id: uuid.UUID
) -> DomainResponse:
    await _assert_recipe_exists(session, recipe_id)
    domain = await _repo.get_domain_by_id(session, domain_id)
    if domain is None or domain.recipe_id != recipe_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")
    return DomainResponse.model_validate(domain)


async def update_domain(
    session: AsyncSession, recipe_id: uuid.UUID, domain_id: uuid.UUID, payload: DomainUpdate
) -> DomainResponse:
    await _assert_recipe_exists(session, recipe_id)
    domain = await _repo.get_domain_by_id(session, domain_id)
    if domain is None or domain.recipe_id != recipe_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")
    updates = payload.model_dump(exclude_unset=True)
    domain = await _repo.update_domain(session, domain=domain, updates=updates)
    return DomainResponse.model_validate(domain)


async def delete_domain(
    session: AsyncSession, recipe_id: uuid.UUID, domain_id: uuid.UUID
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    deleted = await _repo.delete_domain_by_id(session, recipe_id=recipe_id, domain_id=domain_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")


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
    return _unit_to_response(unit)


async def delete_unit(
    session: AsyncSession, recipe_id: uuid.UUID, unit_id: uuid.UUID
) -> None:
    await _assert_recipe_exists(session, recipe_id)
    deleted = await _repo.delete_unit_by_id(session, recipe_id=recipe_id, unit_id=unit_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workload unit not found")


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
    raw_rules = updates.pop("exposure_rules", None)
    exposure_rules = [r.model_dump() for r in raw_rules] if raw_rules is not None else None
    gw = await _repo.update_gateway(
        session, gateway=gw, updates=updates, exposure_rules=exposure_rules
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found",
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
    """Ensure a recipe exists for the given ID."""
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
