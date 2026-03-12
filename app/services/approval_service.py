"""
Approval Service — controls the DRAFT → PENDING_APPROVAL → APPROVED → (publish) flow.

State machine
─────────────
  DRAFT
    │  POST /drafts/{id}/submit
    ▼
  PENDING_APPROVAL  ──(AUTO_APPROVE_RECIPES=true)──▶  APPROVED
    │  POST /drafts/{id}/review  {decision: "approved"}
    ▼
  APPROVED  ──▶  publish allowed
    │  POST /drafts/{id}/review  {decision: "rejected"}
    ▼
  REJECTED  ──(re-submit)──▶  PENDING_APPROVAL

Deployment guard
────────────────
  POST /deployments validates that the referenced RecipeVersion has:
    • is_published == True
    • approval_status == 'APPROVED'
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.recipe import (
    DeploymentValidateResponse,
    ReviewRequest,
    ReviewResponse,
    SubmitForApprovalResponse,
)
from app.core.config import get_settings
from app.models.recipe import ApprovalStatus, RecipeVersion
from app.repositories.recipe_repository import RecipeRepository

settings = get_settings()
_repo = RecipeRepository()


# ─────────────────────────── Step 2 (new) — Submit for approval ──────────────

# ─────────────────────────── Step 2 (new) — Submit for approval ──────────────

async def submit_for_approval(
    session: AsyncSession,
    draft_id: uuid.UUID,
) -> SubmitForApprovalResponse:
    """
    Transition: DRAFT → PENDING_APPROVAL  (or APPROVED when AUTO_APPROVE on).

    Rules
    ─────
    • Recipe must exist.
    • Only DRAFT or REJECTED recipes may be re-submitted.
      (PENDING_APPROVAL / APPROVED recipes are idempotent — return current state.)
    """
    recipe = await _repo.get_draft_by_id_with_approval(session, draft_id)
    if recipe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipe/Draft '{draft_id}' not found",
        )

    current = recipe.approval_status

    # Already at a terminal-enough state — return current status without error
    if current == ApprovalStatus.APPROVED:
        return SubmitForApprovalResponse(
            draft_id=draft_id,
            approval_status=current,
            message="Recipe is already approved.",
        )
    if current == ApprovalStatus.PENDING_APPROVAL:
        return SubmitForApprovalResponse(
            draft_id=draft_id,
            approval_status=current,
            message="Recipe is already pending approval.",
        )

    # DRAFT or REJECTED → move forward
    if settings.AUTO_APPROVE_RECIPES:
        new_status = ApprovalStatus.APPROVED
        message = "Recipe auto-approved and ready to publish."
    else:
        new_status = ApprovalStatus.PENDING_APPROVAL
        message = "Recipe submitted for approval. Awaiting reviewer decision."

    await _repo.update_draft_approval_status(
        session, recipe_id=draft_id, approval_status=new_status
    )
    return SubmitForApprovalResponse(
        recipe_id=draft_id,
        approval_status=new_status,
        message=message,
    )


# ─────────────────────────── Reviewer decision ───────────────────────────────

async def review_draft(
    session: AsyncSession,
    draft_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    payload: ReviewRequest,
) -> ReviewResponse:
    """
    A privileged reviewer approves or rejects a PENDING_APPROVAL recipe.

    Rules
    ─────
    • Recipe must be in PENDING_APPROVAL state.
    • Each review is persisted as an immutable RecipeApproval record.
    """
    recipe = await _repo.get_draft_by_id_with_approval(session, draft_id)
    if recipe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipe/Draft '{draft_id}' not found",
        )

    if recipe.approval_status != ApprovalStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Recipe is in '{recipe.approval_status}' state. "
                "Only PENDING_APPROVAL recipes can be reviewed."
            ),
        )

    # Map reviewer decision string → ApprovalStatus constant
    new_status = (
        ApprovalStatus.APPROVED
        if payload.decision == "approved"
        else ApprovalStatus.REJECTED
    )

    await _repo.update_draft_approval_status(
        session, recipe_id=draft_id, approval_status=new_status
    )
    approval = await _repo.create_approval_record(
        session,
        recipe_id=draft_id,
        reviewer_id=reviewer_id,
        decision=payload.decision,
        comments=payload.comments,
    )

    return ReviewResponse(
        recipe_id=draft_id,
        reviewer_id=reviewer_id,
        decision=payload.decision,
        approval_status=new_status,
        comments=approval.comments,
    )


# ─────────────────────────── Deployment version guard ────────────────────────

async def validate_version_for_deployment(
    session: AsyncSession,
    version_id: uuid.UUID,
) -> DeploymentValidateResponse:
    """
    Called by POST /deployments before creating any deployment record.

    Checks (in order):
      1. Version exists
      2. Version is published  (is_published == True)
      3. Version is approved   (approval_status == 'APPROVED')
    """
    version = await _repo.get_version_by_id(session, version_id)

    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipe version '{version_id}' not found",
        )

    if not version.is_published:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Recipe version not published",
                "recipe_version_id": str(version_id),
            },
        )

    if version.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Recipe version not approved for deployment",
                "recipe_version_id": str(version_id),
                "approval_status": version.approval_status,
            },
        )

    return DeploymentValidateResponse(
        recipe_version_id=version.id,
        version_number=version.version_number,
        approval_status=version.approval_status,
        is_published=version.is_published,
    )


async def validate_version_for_challenge(
    session: AsyncSession,
    version_id: uuid.UUID,
) -> DeploymentValidateResponse:
    """
    Guard used when creating/updating Challenge records.

    Checks:
      1. Version is valid for deployment (exists, published, approved).
      2. Version is the latest version for its recipe (no higher version_number exists).
    """
    result = await validate_version_for_deployment(session, version_id)

    version = await _repo.get_version_by_id(session, version_id)
    if version is None:
        # Should already be handled by validate_version_for_deployment, but keep defensive.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipe version '{version_id}' not found",
        )

    newer_q = await session.execute(
        select(RecipeVersion.version_number)
        .where(
            RecipeVersion.recipe_id == version.recipe_id,
            RecipeVersion.version_number > version.version_number,
        )
        .order_by(RecipeVersion.version_number.desc())
        .limit(1)
    )
    newer = newer_q.scalar_one_or_none()
    if newer is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "NOT_LATEST_DRAFT_VERSION",
                "message": "Exercise instances must be created from the latest version of the recipe.",
                "recipe_id": str(version.recipe_id),
                "requested_version": version.version_number,
                "latest_version": newer,
            },
        )

    return result
