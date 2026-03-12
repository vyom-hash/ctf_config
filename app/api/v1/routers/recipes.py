"""
Recipe API Router — production-ready CTF recipe authoring & runtime API.

Conventions: operation_id per endpoint (e.g. recipes.list, recipes.drafts.create),
consistent error responses (401, 404, 409), pagination via page_token.
URL prefix: /api/v1/recipes
"""
from __future__ import annotations

import uuid
from typing import Annotated, List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.schemas.recipe import (
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
    JumphostUnitInput,
    ListRecipesResponse,
    PublishedRecipeResponse,
    ReviewRequest,
    ReviewResponse,
    SubmitForApprovalResponse,
    ValidationResult,
    WorkloadUnitCreate,
    WorkloadUnitResponse,
    WorkloadUnitUpdate,
)

# Aliases for backward compat within this router
NetworkProfileConfig = GlobalDomainConfig
NetworkProfileResponse = GlobalDomainResponse
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.services import approval_service as _approval_svc
from app.services import recipe_service as _recipe_svc

router = APIRouter(prefix="/recipes", tags=["Recipes"])

RESPONSES_401 = {401: {"description": "Missing or invalid authentication"}}
RESPONSES_404 = {404: {"description": "Resource not found"}}
RESPONSES_409 = {409: {"description": "Conflict (e.g. draft in use)"}}
RESPONSES_DRAFT = {**RESPONSES_401, **RESPONSES_404, **RESPONSES_409}

# ── Dependency aliases ────────────────────────────────────────────────────────
DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]


# ═══════════════════════════════════════════════════════════════════════════════
#  Recipe collection & draft CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "",
    response_model=ListRecipesResponse,
    summary="List recipes (drafts)",
    description="Paginated list of recipe drafts. Use page_token for next page.",
    operation_id="recipes.list",
    responses=RESPONSES_401,
)
async def list_recipes(
    db: DB,
    _: CurrentUser,
    page_token: str | None = None,
    page_size: int = 20,
) -> ListRecipesResponse:
    page = int(page_token) if page_token else 1
    return await _recipe_svc.list_drafts(db, page=page, page_size=min(page_size, 100))


# ── Step 1 — Create draft ─────────────────────────────────────────────────────

@router.post(
    "",
    response_model=DraftResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an empty lab recipe",
    description="Step 1 — Create a new lab recipe; then configure network, domains, units, gateways.",
    operation_id="recipes.create",
    responses=RESPONSES_401,
)
async def create_draft(
    payload: DraftCreate,
    db: DB,
    user_id: CurrentUser,
) -> DraftResponse:
    return await _recipe_svc.create_draft(db, payload, created_by=user_id)


@router.get(
    "/{recipe_id}",
    response_model=DraftDetailResponse,
    summary="Get full recipe detail",
    description="Returns the recipe with all child resources (network profile, domains, units, gateways).",
    operation_id="recipes.get",
    responses=RESPONSES_DRAFT,
)
async def get_draft(
    recipe_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> DraftDetailResponse:
    return await _recipe_svc.get_draft_detail(db, recipe_id)


@router.put(
    "/{recipe_id}",
    response_model=DraftDetailResponse,
    summary="Update recipe metadata",
    description="Update name, description, category.",
    operation_id="recipes.update",
    responses=RESPONSES_DRAFT,
)
async def update_draft(
    recipe_id: uuid.UUID,
    payload: DraftUpdate,
    db: DB,
    _: CurrentUser,
) -> DraftDetailResponse:
    return await _recipe_svc.update_draft(db, recipe_id, payload)


@router.delete(
    "/{recipe_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a lab recipe",
    description="Permanently deletes the recipe. Fails with 409 if any deployment uses a version of this recipe.",
    operation_id="recipes.delete",
    responses=RESPONSES_DRAFT,
)
async def delete_draft(
    recipe_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> Response:
    """Delete a recipe. Fails if any deployment uses a version of this recipe."""
    await _recipe_svc.delete_draft(db, recipe_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Step 2 — Configure network profile ───────────────────────────────────────

@router.put(
    "/{recipe_id}/network-profile",
    response_model=NetworkProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Set network segmentation profile",
    description="Step 2 — Set or replace the network profile (segmentation, subnet, gateway, DNS).",
    operation_id="recipes.networkProfile.set",
    responses=RESPONSES_DRAFT,
)
async def configure_network_profile(
    recipe_id: uuid.UUID,
    payload: NetworkProfileConfig,
    db: DB,
    _: CurrentUser,
) -> NetworkProfileResponse:
    await _recipe_svc.configure_global_domain(db, recipe_id, payload)
    return await _recipe_svc.get_global_domain(db, recipe_id)


@router.get(
    "/{recipe_id}/network-profile",
    response_model=NetworkProfileResponse,
    summary="Get network profile",
    operation_id="recipes.networkProfile.get",
    responses=RESPONSES_DRAFT,
)
async def get_network_profile(
    recipe_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> NetworkProfileResponse:
    return await _recipe_svc.get_global_domain(db, recipe_id)


# ── Step 3 — Network domains ──────────────────────────────────────────────────

@router.post(
    "/{recipe_id}/domains",
    response_model=DomainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add network domain",
    description="Step 3 — Append a network domain to the draft.",
    operation_id="recipes.domains.create",
    responses=RESPONSES_DRAFT,
)
async def add_domain(
    recipe_id: uuid.UUID,
    payload: DomainCreate,
    db: DB,
    _: CurrentUser,
) -> DomainResponse:
    await _recipe_svc.add_domain(db, recipe_id, payload)
    domains = await _recipe_svc.list_domains(db, recipe_id)
    return next(d for d in reversed(domains) if d.name == payload.name)


@router.get(
    "/{recipe_id}/domains",
    response_model=List[DomainResponse],
    summary="List network domains",
    operation_id="recipes.domains.list",
    responses=RESPONSES_DRAFT,
)
async def list_domains(
    recipe_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> List[DomainResponse]:
    return await _recipe_svc.list_domains(db, recipe_id)


@router.get(
    "/{recipe_id}/domains/{domain_id}",
    response_model=DomainResponse,
    summary="Get network domain by ID",
    operation_id="recipes.domains.get",
    responses=RESPONSES_DRAFT,
)
async def get_domain(
    recipe_id: uuid.UUID,
    domain_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> DomainResponse:
    return await _recipe_svc.get_domain(db, recipe_id, domain_id)


@router.patch(
    "/{recipe_id}/domains/{domain_id}",
    response_model=DomainResponse,
    summary="Update network domain (partial)",
    description="Only sent fields are updated.",
    operation_id="recipes.domains.update",
    responses=RESPONSES_DRAFT,
)
async def update_domain(
    recipe_id: uuid.UUID,
    domain_id: uuid.UUID,
    payload: DomainUpdate,
    db: DB,
    _: CurrentUser,
) -> DomainResponse:
    return await _recipe_svc.update_domain(db, recipe_id, domain_id, payload)


@router.delete(
    "/{recipe_id}/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete network domain",
    operation_id="recipes.domains.delete",
    responses=RESPONSES_DRAFT,
)
async def delete_domain(
    recipe_id: uuid.UUID,
    domain_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> Response:
    await _recipe_svc.delete_domain(db, recipe_id, domain_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Step 4 — Workload units ───────────────────────────────────────────────────

@router.post(
    "/{recipe_id}/units",
    response_model=WorkloadUnitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add workload unit",
    description="Step 4 — Append a workload unit (VM/container) to the draft.",
    operation_id="recipes.units.create",
    responses=RESPONSES_DRAFT,
)
async def add_workload_unit(
    recipe_id: uuid.UUID,
    payload: WorkloadUnitCreate,
    db: DB,
    _: CurrentUser,
) -> WorkloadUnitResponse:
    await _recipe_svc.add_workload_unit(db, recipe_id, payload)
    units = await _recipe_svc.list_units(db, recipe_id)
    return next(u for u in reversed(units) if u.name == payload.name)


@router.get(
    "/{recipe_id}/units",
    response_model=List[WorkloadUnitResponse],
    summary="List workload units",
    operation_id="recipes.units.list",
    responses=RESPONSES_DRAFT,
)
async def list_units(
    recipe_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> List[WorkloadUnitResponse]:
    return await _recipe_svc.list_units(db, recipe_id)


@router.get(
    "/{recipe_id}/units/{unit_id}",
    response_model=WorkloadUnitResponse,
    summary="Get workload unit by ID",
    operation_id="recipes.units.get",
    responses=RESPONSES_DRAFT,
)
async def get_unit(
    recipe_id: uuid.UUID,
    unit_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> WorkloadUnitResponse:
    return await _recipe_svc.get_unit(db, recipe_id, unit_id)


@router.patch(
    "/{recipe_id}/units/{unit_id}",
    response_model=WorkloadUnitResponse,
    summary="Update workload unit (partial)",
    description="Only sent fields are updated.",
    operation_id="recipes.units.update",
    responses=RESPONSES_DRAFT,
)
async def update_unit(
    recipe_id: uuid.UUID,
    unit_id: uuid.UUID,
    payload: WorkloadUnitUpdate,
    db: DB,
    _: CurrentUser,
) -> WorkloadUnitResponse:
    return await _recipe_svc.update_unit(db, recipe_id, unit_id, payload)


@router.delete(
    "/{recipe_id}/units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete workload unit",
    operation_id="recipes.units.delete",
    responses=RESPONSES_DRAFT,
)
async def delete_unit(
    recipe_id: uuid.UUID,
    unit_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> Response:
    await _recipe_svc.delete_unit(db, recipe_id, unit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Step 5 — Gateways ─────────────────────────────────────────────────────────

@router.post(
    "/{recipe_id}/gateways",
    response_model=GatewayResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add access gateway",
    description="Step 5 — Append an access gateway with exposure rules.",
    operation_id="recipes.gateways.create",
    responses=RESPONSES_DRAFT,
)
async def add_gateway(
    recipe_id: uuid.UUID,
    payload: GatewayCreate,
    db: DB,
    _: CurrentUser,
) -> GatewayResponse:
    await _recipe_svc.add_gateway(db, recipe_id, payload)
    gateways = await _recipe_svc.list_gateways(db, recipe_id)
    return next(g for g in reversed(gateways) if g.gateway_key == payload.gateway_key)


@router.get(
    "/{recipe_id}/gateways",
    response_model=List[GatewayResponse],
    summary="List gateways",
    operation_id="recipes.gateways.list",
    responses=RESPONSES_DRAFT,
)
async def list_gateways(
    recipe_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> List[GatewayResponse]:
    return await _recipe_svc.list_gateways(db, recipe_id)


@router.get(
    "/{recipe_id}/gateways/{gateway_id}",
    response_model=GatewayResponse,
    summary="Get gateway by ID",
    operation_id="recipes.gateways.get",
    responses=RESPONSES_DRAFT,
)
async def get_gateway(
    recipe_id: uuid.UUID,
    gateway_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> GatewayResponse:
    return await _recipe_svc.get_gateway(db, recipe_id, gateway_id)


@router.patch(
    "/{recipe_id}/gateways/{gateway_id}",
    response_model=GatewayResponse,
    summary="Update gateway",
    description="exposure_rules are fully replaced when provided.",
    operation_id="recipes.gateways.update",
    responses=RESPONSES_DRAFT,
)
async def update_gateway(
    recipe_id: uuid.UUID,
    gateway_id: uuid.UUID,
    payload: GatewayUpdate,
    db: DB,
    _: CurrentUser,
) -> GatewayResponse:
    return await _recipe_svc.update_gateway(db, recipe_id, gateway_id, payload)


@router.delete(
    "/{recipe_id}/gateways/{gateway_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete gateway",
    operation_id="recipes.gateways.delete",
    responses=RESPONSES_DRAFT,
)
async def delete_gateway(
    recipe_id: uuid.UUID,
    gateway_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> Response:
    await _recipe_svc.delete_gateway(db, recipe_id, gateway_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{recipe_id}/jumphost",
    summary="Set jumphost unit",
    description="Configure the jumphost unit for this recipe. Stored as part of the recipe spec and included in the published snapshot.",
    operation_id="recipes.jumphost.set",
    responses=RESPONSES_DRAFT,
)
async def set_jumphost_unit(
    recipe_id: uuid.UUID,
    payload: JumphostUnitInput,
    db: DB,
    _: CurrentUser,
) -> dict:
    return await _recipe_svc.set_jumphost_unit(db, recipe_id, payload)


@router.post(
    "/{recipe_id}/validate",
    response_model=ValidationResult,
    summary="Validate draft",
    description="Step 8 — Run all structural validations without publishing.",
    operation_id="recipes.validate",
    responses=RESPONSES_DRAFT,
)
async def validate_draft(
    recipe_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> ValidationResult:
    return await _recipe_svc.validate_draft(db, recipe_id)


# ── Step 8b — Submit for approval ────────────────────────────────────────────
#
# Flow (AUTO_APPROVE_RECIPES = true):   DRAFT → APPROVED
# Flow (AUTO_APPROVE_RECIPES = false):  DRAFT → PENDING_APPROVAL → (reviewer) → APPROVED

@router.post(
    "/{recipe_id}/submit",
    response_model=SubmitForApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit draft for approval",
    description="Submits the draft for approval. Auto-approves when AUTO_APPROVE_RECIPES=true.",
    operation_id="recipes.submit",
    responses=RESPONSES_DRAFT,
)
async def submit_for_approval(
    recipe_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> SubmitForApprovalResponse:
    return await _approval_svc.submit_for_approval(db, recipe_id)


# ── Step 8c — Reviewer decision (skipped when AUTO_APPROVE_RECIPES=true) ──────

@router.post(
    "/{recipe_id}/review",
    response_model=ReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Review draft (approve/reject)",
    description="Reviewer approves or rejects a PENDING_APPROVAL draft.",
    operation_id="recipes.review",
    responses=RESPONSES_DRAFT,
)
async def review_draft(
    recipe_id: uuid.UUID,
    payload: ReviewRequest,
    db: DB,
    reviewer_id: CurrentUser,
) -> ReviewResponse:
    return await _approval_svc.review_draft(db, recipe_id, reviewer_id, payload)


# ── Step 9 — Publish draft (immutable version) ────────────────────────────────

@router.post(
    "/{recipe_id}/publish",
    response_model=PublishedRecipeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publish draft",
    description="Step 9 — Validate, snapshot, and publish the draft as a versioned recipe.",
    operation_id="recipes.publish",
    responses=RESPONSES_DRAFT,
)
async def publish_draft(
    recipe_id: uuid.UUID,
    db: DB,
    _: CurrentUser,
) -> PublishedRecipeResponse:
    return await _recipe_svc.publish_draft(db, recipe_id)


# No runtime endpoints here: flag submission and leaderboard live on exercise instances.
