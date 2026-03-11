"""
Unit tests for deployment API schemas.

Covers: DeploymentCreateRequest validation (both modes, invalid combinations),
AccessConfig, AccessGatewayConfig, DeploymentUpdateRequest, response models.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.api.schemas.deployment import (
    AccessConfig,
    AccessGatewayConfig,
    DeploymentCreateRequest,
    DeploymentCreateResponse,
    DeploymentResponse,
    DeploymentUpdateRequest,
)


class TestDeploymentCreateRequest:
    """POST body: either recipe_version_id or recipe_id + recipe_version + params."""

    def test_valid_by_version_id(self) -> None:
        req = DeploymentCreateRequest(
            recipe_version_id=uuid.uuid4(),
            member_ids=[],
        )
        assert req.recipe_version_id is not None
        assert req.recipe_id is None

    def test_valid_by_version_id_with_optional_fields(self) -> None:
        req = DeploymentCreateRequest(
            recipe_version_id=uuid.uuid4(),
            name="My deployment",
            member_ids=[uuid.uuid4()],
            access=AccessConfig(
                entry_method="gateway",
                ssh_public_key_ref="secret://key",
                floating_ip_enabled=False,
                remote_console_enabled=True,
            ),
        )
        assert req.name == "My deployment"
        assert req.access is not None

    def test_valid_by_draft_with_required_params(self) -> None:
        req = DeploymentCreateRequest(
            recipe_id=uuid.uuid4(),
            recipe_version=1,
            initiator_user=uuid.uuid4(),
            experience_type="selfpaced",
            duration_hours=24,
            access_mode="solo",
            member_ids=[],
        )
        assert req.recipe_id is not None
        assert req.recipe_version == 1
        assert req.experience_type == "selfpaced"
        assert req.duration_hours == 24
        assert req.access_mode == "solo"

    def test_invalid_both_modes_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            DeploymentCreateRequest(
                recipe_version_id=uuid.uuid4(),
                recipe_id=uuid.uuid4(),
                recipe_version=1,
                initiator_user=uuid.uuid4(),
                experience_type="x",
                duration_hours=1,
                access_mode="y",
                member_ids=[],
            )
        assert "Provide either" in str(exc_info.value)

    def test_invalid_neither_mode_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            DeploymentCreateRequest(
                member_ids=[],
            )
        assert "Provide either" in str(exc_info.value)

    def test_draft_mode_requires_initiator_experience_duration_access_mode(self) -> None:
        with pytest.raises(ValidationError):
            DeploymentCreateRequest(
                recipe_id=uuid.uuid4(),
                recipe_version=1,
                initiator_user=None,
                experience_type="selfpaced",
                duration_hours=24,
                access_mode="solo",
                member_ids=[],
            )
        with pytest.raises(ValidationError):
            DeploymentCreateRequest(
                recipe_id=uuid.uuid4(),
                recipe_version=1,
                initiator_user=uuid.uuid4(),
                experience_type=None,
                duration_hours=24,
                access_mode="solo",
                member_ids=[],
            )
        with pytest.raises(ValidationError):
            DeploymentCreateRequest(
                recipe_id=uuid.uuid4(),
                recipe_version=1,
                initiator_user=uuid.uuid4(),
                experience_type="selfpaced",
                duration_hours=None,
                access_mode="solo",
                member_ids=[],
            )
        with pytest.raises(ValidationError):
            DeploymentCreateRequest(
                recipe_id=uuid.uuid4(),
                recipe_version=1,
                initiator_user=uuid.uuid4(),
                experience_type="selfpaced",
                duration_hours=24,
                access_mode=None,
                member_ids=[],
            )

    def test_recipe_version_ge_1(self) -> None:
        with pytest.raises(ValidationError):
            DeploymentCreateRequest(
                recipe_id=uuid.uuid4(),
                recipe_version=0,
                initiator_user=uuid.uuid4(),
                experience_type="x",
                duration_hours=1,
                access_mode="y",
                member_ids=[],
            )


class TestAccessConfig:
    """Jumphost access config."""

    def test_required_fields(self) -> None:
        cfg = AccessConfig(
            entry_method="gateway",
            ssh_public_key_ref="secret://org/default-ssh-key",
        )
        assert cfg.entry_method == "gateway"
        assert cfg.floating_ip_enabled is False
        assert cfg.remote_console_enabled is True

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            AccessConfig(
                entry_method="gateway",
                ssh_public_key_ref="secret://key",
                unknown_field="x",
            )


class TestAccessGatewayConfig:
    """Access gateway instance config."""

    def test_required_fields(self) -> None:
        cfg = AccessGatewayConfig(
            attached_segment="internal",
            image_profile="gateway-standard",
            host_offset=5,
            flavor_profile="medium",
        )
        assert cfg.enabled is True
        assert cfg.vnc_enabled is True
        assert cfg.floating_ip_enabled is True


class TestDeploymentUpdateRequest:
    """PATCH body: optional name, access, target_env, recipe_spec, exercises."""

    def test_all_optional(self) -> None:
        req = DeploymentUpdateRequest()
        assert req.model_dump(exclude_unset=True) == {}

    def test_partial_update(self) -> None:
        req = DeploymentUpdateRequest(name="New name")
        assert req.name == "New name"
        assert req.access is None


class TestDeploymentCreateResponse:
    """201 response shape."""

    def test_provider_profile_none_when_target_env_set(self) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        r = DeploymentCreateResponse(
            deployment_id=uuid.uuid4(),
            recipe_version_id=uuid.uuid4(),
            status="ALLOCATING",
            expires_at=now,
            team_size=1,
            created_at=now,
            target_env="openstack-dev",
        )
        assert r.provider_profile is None

    def test_provider_profile_can_be_set_when_no_target_env(self) -> None:
        from datetime import datetime, timezone

        from app.core.deployment_constants import PROVIDER_PROFILE

        now = datetime.now(timezone.utc)
        r = DeploymentCreateResponse(
            deployment_id=uuid.uuid4(),
            recipe_version_id=uuid.uuid4(),
            status="ALLOCATING",
            expires_at=now,
            team_size=1,
            created_at=now,
            provider_profile=dict(PROVIDER_PROFILE),
        )
        assert r.provider_profile is not None
        assert "provider_type" in r.provider_profile or "auth_url" in r.provider_profile


class TestDeploymentResponse:
    """GET/POST response shape (standard one; recipe_spec only, no duplicate recipe)."""

    def test_recipe_spec_optional(self) -> None:
        from datetime import datetime, timezone

        r = DeploymentResponse(
            deployment_id=uuid.uuid4(),
            recipe_version_id=uuid.uuid4(),
            status="RUNNING",
            expires_at=datetime.now(timezone.utc),
            team_size=1,
            member_ids=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            recipe_spec=None,
        )
        assert r.recipe_spec is None
        assert "provider_profile" in r.model_dump()
