"""
Unit tests for deployment service.

Covers: _build_recipe_from_spec, _to_response, create returns standard DeploymentResponse.
get_deployment, update_deployment, create_deployment, create_deployment_from_draft,
create_deployment_unified, _team_size_and_validate, _expires_at,
_check_recipe_version, _ensure_draft_approved, Redis gate.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.schemas.deployment import (
    AccessConfig,
    AccessGatewayConfig,
    DeploymentCreateFromDraftRequest,
    DeploymentCreateRequest,
    DeploymentUpdateRequest,
)
from app.models.deployment import DeploymentStatus
from app.models.recipe import ApprovalStatus
from app.services import deployment_service as svc


# ───────────────────────── _build_recipe_from_spec ─────────────────────────

class TestBuildRecipeFromSpec:
    """Pure function: recipe_spec + recipe_id -> recipe-style dict."""

    def test_flattens_metadata_and_sets_approval_status(
        self,
        sample_recipe_spec: dict,
    ) -> None:
        recipe_id = uuid.uuid4()
        out = svc._build_recipe_from_spec(sample_recipe_spec, recipe_id)
        assert out["recipe_id"] == str(recipe_id)
        assert out["name"] == "stealth-ops-ig05"
        assert out["description"] == "Auto-generated CTF scenario"
        assert out["category"] == "CTF"
        assert out["approval_status"] == "APPROVED"

    def test_recipe_id_none_when_not_provided(self, sample_recipe_spec: dict) -> None:
        out = svc._build_recipe_from_spec(sample_recipe_spec, None)
        assert out["recipe_id"] is None

    def test_copies_network_profile_domains_workload_units(
        self,
        sample_recipe_spec: dict,
    ) -> None:
        recipe_id = uuid.uuid4()
        out = svc._build_recipe_from_spec(sample_recipe_spec, recipe_id)
        assert out["network_profile"] == sample_recipe_spec["network_profile"]
        assert out["domains"] == sample_recipe_spec["domains"]
        assert len(out["workload_units"]) == 2

    def test_converts_exposure_rules_unit_id_to_unit_key(
        self,
        sample_recipe_spec: dict,
    ) -> None:
        recipe_id = uuid.uuid4()
        out = svc._build_recipe_from_spec(sample_recipe_spec, recipe_id)
        gateways = out["gateways"]
        assert len(gateways) == 1
        rules = gateways[0]["exposure_rules"]
        assert len(rules) == 2
        assert rules[0]["unit_key"] == "web-server-01"
        assert rules[1]["unit_key"] == "db-server-01"
        assert rules[0]["internal_port"] == 80
        assert rules[1]["internal_port"] == 5432
        assert "id" in rules[0]
        assert gateways[0].get("is_active") is True

    def test_empty_metadata_yields_none_fields(self) -> None:
        spec = {"metadata": {}, "domains": [], "workload_units": [], "gateways": []}
        out = svc._build_recipe_from_spec(spec, uuid.uuid4())
        assert out["name"] is None
        assert out["approval_status"] == "APPROVED"
        assert out["gateways"] == []

    def test_missing_metadata_uses_empty_dict(self) -> None:
        spec = {"domains": [], "workload_units": [], "gateways": []}
        out = svc._build_recipe_from_spec(spec, None)
        assert out["name"] is None
        assert out["approval_status"] == "APPROVED"

    def test_exposure_rule_unknown_unit_id_falls_back_to_str(self) -> None:
        spec = {
            "metadata": {},
            "domains": [],
            "workload_units": [{"id": "a", "unit_key": "only-one"}],
            "gateways": [
                {
                    "id": "gw1",
                    "gateway_key": "g",
                    "gateway_type": "vyos",
                    "runtime_profile": "oe:gateway",
                    "resource_tier": "md",
                    "exposure_rules": [
                        {"unit_id": "unknown-uuid", "internal_port": 22, "transport_protocol": "tcp"},
                    ],
                },
            ],
        }
        out = svc._build_recipe_from_spec(spec, None)
        assert out["gateways"][0]["exposure_rules"][0]["unit_key"] == "unknown-uuid"


# ───────────────────────── _to_response ────────────────────────────────────

class TestToResponse:
    """Build DeploymentResponse from ORM-like object."""

    def test_includes_all_fields_and_recipe_spec_only(
        self,
        mock_deployment_orm: MagicMock,
    ) -> None:
        resp = svc._to_response(mock_deployment_orm)
        assert resp.deployment_id == mock_deployment_orm.id
        assert resp.recipe_version_id == mock_deployment_orm.recipe_version_id
        assert resp.status == "ALLOCATING"
        assert resp.team_size == 1
        assert resp.name is None
        assert resp.member_ids == []
        assert resp.access is not None
        assert resp.recipe_id == mock_deployment_orm.recipe_id
        assert resp.experience_type == "selfpaced"
        assert resp.duration_hours == 24
        assert resp.access_mode == "solo"
        assert resp.recipe_spec is not None
        assert "access_gateway" not in (resp.recipe_spec or {})
        assert "metadata" in (resp.recipe_spec or {})
        assert "provider_profile" in resp.model_dump()

    def test_no_recipe_spec_when_empty(
        self,
        mock_deployment_orm_no_recipe_spec: MagicMock,
    ) -> None:
        resp = svc._to_response(mock_deployment_orm_no_recipe_spec)
        assert resp.recipe_spec is None
        assert resp.name == "My deployment"
        assert resp.access is None


class TestCreateReturnsStandardResponse:
    """Create deployment returns same DeploymentResponse shape as GET."""

    def test_create_response_has_recipe_spec_no_recipe_key(self, mock_deployment_orm: MagicMock) -> None:
        resp = svc._to_response(mock_deployment_orm)
        assert hasattr(resp, "recipe_spec")
        assert not hasattr(resp, "recipe") or getattr(resp, "recipe", None) is None


# ───────────────────────── get_deployment ─────────────────────────────────

class TestGetDeployment:
    """get_deployment(session, deployment_id)."""

    @pytest.mark.asyncio
    async def test_404_when_not_found(self) -> None:
        session = AsyncMock()
        with patch.object(svc._repo, "get_by_id", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await svc.get_deployment(session, uuid.uuid4())
            assert exc_info.value.status_code == 404
            assert "Deployment not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_200_returns_response(
        self,
        mock_deployment_orm: MagicMock,
    ) -> None:
        session = AsyncMock()
        dep_id = mock_deployment_orm.id
        # Mock session.execute() for the ExerciseInstance query inside get_deployment
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        with patch.object(svc._repo, "get_by_id", new_callable=AsyncMock, return_value=mock_deployment_orm):
            resp = await svc.get_deployment(session, dep_id)
        assert resp.deployment_id == dep_id
        assert resp.recipe_spec is not None


# ───────────────────────── update_deployment ────────────────────────────────

class TestUpdateDeployment:
    """update_deployment(session, deployment_id, payload)."""

    @pytest.mark.asyncio
    async def test_404_when_not_found(self) -> None:
        session = AsyncMock()
        with patch.object(svc._repo, "get_by_id", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await svc.update_deployment(session, uuid.uuid4(), DeploymentUpdateRequest(name="x"))
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_404_when_update_returns_none(self) -> None:
        session = AsyncMock()
        dep_id = uuid.uuid4()
        with patch.object(svc._repo, "get_by_id", new_callable=AsyncMock, return_value=MagicMock()):
            with patch.object(svc._repo, "update", new_callable=AsyncMock, return_value=None):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.update_deployment(session, dep_id, DeploymentUpdateRequest(name="x"))
                assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_200_returns_updated_response(
        self,
        mock_deployment_orm: MagicMock,
    ) -> None:
        session = AsyncMock()
        dep_id = mock_deployment_orm.id
        # Mock session.execute() for the ExerciseInstance query inside update_deployment
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        with patch.object(svc._repo, "get_by_id", new_callable=AsyncMock, return_value=mock_deployment_orm):
            with patch.object(svc._repo, "update", new_callable=AsyncMock, return_value=mock_deployment_orm):
                resp = await svc.update_deployment(
                    session, dep_id, DeploymentUpdateRequest(name="Updated")
                )
        assert resp.deployment_id == dep_id


# ───────────────────────── create_deployment (by version_id) ───────────────

class TestCreateDeployment:
    """create_deployment with recipe_version_id."""

    @pytest.mark.asyncio
    async def test_400_when_recipe_version_id_none(self) -> None:
        session = AsyncMock()
        # Build request that bypasses validator (e.g. internal call with only version mode but None)
        req = DeploymentCreateRequest.model_construct(recipe_version_id=None, member_ids=[])
        with pytest.raises(HTTPException) as exc_info:
            await svc.create_deployment(session, req, None, None)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_409_when_team_size_violation(self) -> None:
        session = AsyncMock()
        vid = uuid.uuid4()
        req = DeploymentCreateRequest(recipe_version_id=vid, member_ids=[uuid.uuid4(), uuid.uuid4()])

        def validate_team_size(member_count: int) -> None:
            if member_count > 1:
                raise ValueError("Teams are disabled; only one member allowed")

        with patch("app.services.deployment_service.get_deployment_constraints") as gdc:
            gdc.return_value.team_configuration.enabled = False
            gdc.return_value.team_configuration.validate_team_size = validate_team_size
            with pytest.raises(HTTPException) as exc_info:
                await svc.create_deployment(session, req, None, None)
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_404_when_version_not_found(self) -> None:
        session = AsyncMock()
        vid = uuid.uuid4()
        req = DeploymentCreateRequest(recipe_version_id=vid, member_ids=[])
        with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await svc.create_deployment(session, req, None, None)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_422_when_version_not_published(self) -> None:
        session = AsyncMock()
        vid = uuid.uuid4()
        req = DeploymentCreateRequest(recipe_version_id=vid, member_ids=[])
        version = MagicMock(is_published=False, approval_status=ApprovalStatus.APPROVED, recipe_id=None)
        with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=version):
            with pytest.raises(HTTPException) as exc_info:
                await svc.create_deployment(session, req, None, None)
            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_403_when_version_not_approved(self) -> None:
        session = AsyncMock()
        vid = uuid.uuid4()
        req = DeploymentCreateRequest(recipe_version_id=vid, member_ids=[])
        version = MagicMock(is_published=True, approval_status=ApprovalStatus.PENDING_APPROVAL, recipe_id=None)
        with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=version):
            with pytest.raises(HTTPException) as exc_info:
                await svc.create_deployment(session, req, None, None)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_500_when_snapshot_missing(self) -> None:
        session = AsyncMock()
        vid = uuid.uuid4()
        recipe_id = uuid.uuid4()
        req = DeploymentCreateRequest(recipe_version_id=vid, member_ids=[])
        version = MagicMock(is_published=True, approval_status=ApprovalStatus.APPROVED, recipe_id=recipe_id)
        recipe = MagicMock(approval_status=ApprovalStatus.APPROVED)
        with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=version):
            with patch.object(svc._recipe_repo, "get_full_recipe", new_callable=AsyncMock, return_value=recipe):
                with patch.object(svc._recipe_repo, "get_snapshot_by_version_id", new_callable=AsyncMock, return_value=None):
                    with pytest.raises(HTTPException) as exc_info:
                        await svc.create_deployment(session, req, None, None)
                    assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_201_creates_and_returns(
        self,
        mock_deployment_orm: MagicMock,
        sample_recipe_spec: dict,
    ) -> None:
        session = AsyncMock()
        vid = uuid.uuid4()
        draft_id = uuid.uuid4()
        req = DeploymentCreateRequest(recipe_version_id=vid, member_ids=[])
        version = MagicMock(is_published=True, approval_status=ApprovalStatus.APPROVED, recipe_id=draft_id)
        draft = MagicMock(approval_status=ApprovalStatus.APPROVED)
        mock_deployment_orm.recipe_version_id = vid
        with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=version):
            with patch.object(svc._recipe_repo, "get_full_recipe", new_callable=AsyncMock, return_value=draft):
                with patch.object(svc._recipe_repo, "get_snapshot_by_version_id", new_callable=AsyncMock, return_value=sample_recipe_spec):
                    with patch.object(svc._repo, "acquire_deployment_lock", new_callable=AsyncMock):
                        with patch.object(svc._repo, "count_running_and_allocating", new_callable=AsyncMock, return_value=0):
                            with patch.object(svc, "_load_exercises_json_for_version", new_callable=AsyncMock, return_value=None):
                                with patch.object(svc._repo, "create", new_callable=AsyncMock, return_value=mock_deployment_orm):
                                    resp = await svc.create_deployment(session, req, uuid.uuid4(), None)
        assert resp.deployment_id == mock_deployment_orm.id
        assert resp.status == DeploymentStatus.ALLOCATING


# ───────────────────────── create_deployment_from_draft ─────────────────────

class TestCreateDeploymentFromDraft:
    """create_deployment_from_draft(session, request, redis)."""

    @pytest.mark.asyncio
    async def test_404_when_draft_not_found(self) -> None:
        session = AsyncMock()
        req = DeploymentCreateFromDraftRequest(
            recipe_id=uuid.uuid4(),
            recipe_version=1,
            initiator_user=uuid.uuid4(),
            experience_type="selfpaced",
            duration_hours=24,
            access_mode="solo",
        )
        with patch.object(svc._recipe_repo, "get_full_recipe", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await svc.create_deployment_from_draft(session, req, None)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_when_draft_not_approved(self) -> None:
        session = AsyncMock()
        recipe_id = uuid.uuid4()
        req = DeploymentCreateFromDraftRequest(
            recipe_id=recipe_id,
            recipe_version=1,
            initiator_user=uuid.uuid4(),
            experience_type="selfpaced",
            duration_hours=24,
            access_mode="solo",
        )
        recipe = MagicMock(approval_status=ApprovalStatus.PENDING_APPROVAL)
        with patch.object(svc._recipe_repo, "get_full_recipe", new_callable=AsyncMock, return_value=recipe):
            with pytest.raises(HTTPException) as exc_info:
                await svc.create_deployment_from_draft(session, req, None)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_404_when_version_not_found_for_draft_and_number(self) -> None:
        session = AsyncMock()
        recipe_id = uuid.uuid4()
        req = DeploymentCreateFromDraftRequest(
            recipe_id=recipe_id,
            recipe_version=1,
            initiator_user=uuid.uuid4(),
            experience_type="selfpaced",
            duration_hours=24,
            access_mode="solo",
        )
        recipe = MagicMock(approval_status=ApprovalStatus.APPROVED)
        with patch.object(svc._recipe_repo, "get_full_recipe", new_callable=AsyncMock, return_value=recipe):
            with patch.object(svc._recipe_repo, "get_version_by_draft_and_number", new_callable=AsyncMock, return_value=None):
                with pytest.raises(HTTPException) as exc_info:
                    await svc.create_deployment_from_draft(session, req, None)
                assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_201_creates_from_draft(
        self,
        mock_deployment_orm: MagicMock,
        sample_recipe_spec: dict,
    ) -> None:
        session = AsyncMock()
        recipe_id = uuid.uuid4()
        version_id = uuid.uuid4()
        req = DeploymentCreateFromDraftRequest(
            recipe_id=recipe_id,
            recipe_version=1,
            initiator_user=uuid.uuid4(),
            experience_type="selfpaced",
            duration_hours=24,
            access_mode="solo",
        )
        recipe = MagicMock(approval_status=ApprovalStatus.APPROVED)
        version = MagicMock(id=version_id, is_published=True, approval_status=ApprovalStatus.APPROVED)
        with patch.object(svc._recipe_repo, "get_full_recipe", new_callable=AsyncMock, return_value=recipe):
            with patch.object(svc._recipe_repo, "get_version_by_draft_and_number", new_callable=AsyncMock, return_value=version):
                with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=version):
                    with patch.object(svc._recipe_repo, "get_snapshot_by_version_id", new_callable=AsyncMock, return_value=sample_recipe_spec):
                        with patch.object(svc._repo, "acquire_deployment_lock", new_callable=AsyncMock):
                            with patch.object(svc._repo, "count_running_and_allocating", new_callable=AsyncMock, return_value=0):
                                with patch.object(svc, "_load_exercises_json_for_version", new_callable=AsyncMock, return_value=None):
                                    with patch.object(svc._repo, "create", new_callable=AsyncMock, return_value=mock_deployment_orm):
                                        resp = await svc.create_deployment_from_draft(session, req, None)
        assert resp.deployment_id == mock_deployment_orm.id
        assert resp.status == DeploymentStatus.ALLOCATING


# ───────────────────────── create_deployment_unified ──────────────────────

class TestCreateDeploymentUnified:
    """Single entry: dispatches to by version_id or from_draft."""

    @pytest.mark.asyncio
    async def test_dispatches_to_create_deployment_when_recipe_version_id_set(
        self,
        mock_deployment_orm: MagicMock,
        sample_recipe_spec: dict,
    ) -> None:
        session = AsyncMock()
        vid = uuid.uuid4()
        req = DeploymentCreateRequest(recipe_version_id=vid, member_ids=[])
        version = MagicMock(is_published=True, approval_status=ApprovalStatus.APPROVED, recipe_id=None)
        with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=version):
            with patch.object(svc._recipe_repo, "get_snapshot_by_version_id", new_callable=AsyncMock, return_value=sample_recipe_spec):
                with patch.object(svc._repo, "acquire_deployment_lock", new_callable=AsyncMock):
                    with patch.object(svc._repo, "count_running_and_allocating", new_callable=AsyncMock, return_value=0):
                        with patch.object(svc, "_load_exercises_json_for_version", new_callable=AsyncMock, return_value=None):
                            with patch.object(svc._repo, "create", new_callable=AsyncMock, return_value=mock_deployment_orm):
                                resp = await svc.create_deployment_unified(session, req, None, None)
        assert resp.deployment_id == mock_deployment_orm.id

    @pytest.mark.asyncio
    async def test_dispatches_to_from_draft_when_recipe_and_version_set(
        self,
        mock_deployment_orm: MagicMock,
        sample_recipe_spec: dict,
    ) -> None:
        session = AsyncMock()
        recipe_id = uuid.uuid4()
        version_id = uuid.uuid4()
        req = DeploymentCreateRequest(
            recipe_id=recipe_id,
            recipe_version=1,
            initiator_user=uuid.uuid4(),
            experience_type="selfpaced",
            duration_hours=24,
            access_mode="solo",
            member_ids=[],
        )
        recipe = MagicMock(approval_status=ApprovalStatus.APPROVED)
        version = MagicMock(id=version_id, is_published=True, approval_status=ApprovalStatus.APPROVED)
        with patch.object(svc._recipe_repo, "get_full_recipe", new_callable=AsyncMock, return_value=recipe):
            with patch.object(svc._recipe_repo, "get_version_by_draft_and_number", new_callable=AsyncMock, return_value=version):
                with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=version):
                    with patch.object(svc._recipe_repo, "get_snapshot_by_version_id", new_callable=AsyncMock, return_value=sample_recipe_spec):
                        with patch.object(svc._repo, "acquire_deployment_lock", new_callable=AsyncMock):
                            with patch.object(svc._repo, "count_running_and_allocating", new_callable=AsyncMock, return_value=0):
                                with patch.object(svc, "_load_exercises_json_for_version", new_callable=AsyncMock, return_value=None):
                                    with patch.object(svc._repo, "create", new_callable=AsyncMock, return_value=mock_deployment_orm):
                                        resp = await svc.create_deployment_unified(session, req, None, None)
        assert resp.deployment_id == mock_deployment_orm.id


# ───────────────────────── helpers ─────────────────────────────────────────

class TestTeamSizeAndValidate:
    """_team_size_and_validate(request)."""

    def test_returns_1_when_teams_disabled_and_empty_members(self) -> None:
        with patch("app.services.deployment_service.get_deployment_constraints") as gdc:
            gdc.return_value.team_configuration.enabled = False
            gdc.return_value.team_configuration.validate_team_size = lambda n: None
            req = DeploymentCreateRequest(recipe_version_id=uuid.uuid4(), member_ids=[])
            assert svc._team_size_and_validate(req) == 1

    def test_raises_when_teams_disabled_and_multi_member(self) -> None:
        with patch("app.services.deployment_service.get_deployment_constraints") as gdc:
            def validate(n: int) -> None:
                if n > 1:
                    raise ValueError("Teams are disabled; only one member allowed")
            gdc.return_value.team_configuration.enabled = False
            gdc.return_value.team_configuration.validate_team_size = validate
            req = DeploymentCreateRequest(recipe_version_id=uuid.uuid4(), member_ids=[uuid.uuid4(), uuid.uuid4()])
            with pytest.raises(ValueError, match="only one member"):
                svc._team_size_and_validate(req)


class TestExpiresAt:
    """_expires_at(constraints)."""

    def test_returns_future_datetime(self) -> None:
        with patch("app.services.deployment_service.get_deployment_constraints") as gdc:
            gdc.return_value.auto_expire_minutes = 120
            exp = svc._expires_at(gdc.return_value)
        assert exp.tzinfo is not None
        assert exp > datetime.now(timezone.utc)


class TestCheckRecipeVersion:
    """_check_recipe_version(session, recipe_version_id)."""

    @pytest.mark.asyncio
    async def test_404_when_version_missing(self) -> None:
        session = AsyncMock()
        with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await svc._check_recipe_version(session, uuid.uuid4())
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_422_when_not_published(self) -> None:
        session = AsyncMock()
        version = MagicMock(is_published=False, approval_status=ApprovalStatus.APPROVED)
        with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=version):
            with pytest.raises(HTTPException) as exc_info:
                await svc._check_recipe_version(session, uuid.uuid4())
            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_403_when_not_approved(self) -> None:
        session = AsyncMock()
        version = MagicMock(is_published=True, approval_status=ApprovalStatus.PENDING_APPROVAL)
        with patch.object(svc._recipe_repo, "get_version_by_id", new_callable=AsyncMock, return_value=version):
            with pytest.raises(HTTPException) as exc_info:
                await svc._check_recipe_version(session, uuid.uuid4())
            assert exc_info.value.status_code == 403


class TestEnsureRecipeApproved:
    """_ensure_recipe_approved(session, draft_id)."""

    @pytest.mark.asyncio
    async def test_404_when_draft_missing(self) -> None:
        session = AsyncMock()
        with patch.object(svc._recipe_repo, "get_full_recipe", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await svc._ensure_recipe_approved(session, uuid.uuid4())
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_when_draft_not_approved(self) -> None:
        session = AsyncMock()
        draft = MagicMock(approval_status=ApprovalStatus.PENDING_APPROVAL)
        with patch.object(svc._recipe_repo, "get_full_recipe", new_callable=AsyncMock, return_value=draft):
            with pytest.raises(HTTPException) as exc_info:
                await svc._ensure_recipe_approved(session, uuid.uuid4())
            assert exc_info.value.status_code == 403


class TestDeleteDeployment:
    """delete_deployment(session, deployment_id)."""

    @pytest.mark.asyncio
    async def test_404_when_not_found(self) -> None:
        session = AsyncMock()
        with patch.object(svc._repo, "get_by_id", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await svc.delete_deployment(session, uuid.uuid4())
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_deletes_when_found(self) -> None:
        session = AsyncMock()
        dep_id = uuid.uuid4()
        deployment = MagicMock(id=dep_id)
        with patch.object(svc._repo, "get_by_id", new_callable=AsyncMock, return_value=deployment):
            with patch.object(svc._repo, "delete_by_id", new_callable=AsyncMock) as mock_del:
                await svc.delete_deployment(session, dep_id)
                mock_del.assert_awaited_once_with(session, dep_id)


class TestRedisGate:
    """_redis_incr_gate and _redis_decr."""

    @pytest.mark.asyncio
    async def test_redis_incr_gate_allows_when_under_limit(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.incr = AsyncMock(return_value=1)
        with patch("app.services.deployment_service.get_deployment_constraints") as gdc:
            gdc.return_value.maximum_concurrent_deployments = 1000
            result = await svc._redis_incr_gate(redis_mock)
        assert result is True
        redis_mock.decr.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_incr_gate_rejects_and_decrements_when_over_limit(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.incr = AsyncMock(return_value=1001)
        redis_mock.decr = AsyncMock()
        with patch("app.services.deployment_service.get_deployment_constraints") as gdc:
            gdc.return_value.maximum_concurrent_deployments = 1000
            result = await svc._redis_incr_gate(redis_mock)
        assert result is False
        redis_mock.decr.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_decr_calls_decr(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.decr = AsyncMock()
        await svc._redis_decr(redis_mock)
        redis_mock.decr.assert_called_once()
