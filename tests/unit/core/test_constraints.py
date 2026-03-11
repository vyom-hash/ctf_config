"""
Unit tests for deployment constraints.

Covers: TeamConfiguration.validate_team_size, get_deployment_constraints.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.constraints import (
    DeploymentConstraints,
    TeamConfiguration,
    get_deployment_constraints,
)


class TestTeamConfiguration:
    """validate_team_size(member_count)."""

    def test_teams_disabled_allows_one_member(self) -> None:
        tc = TeamConfiguration(enabled=False, minimum_members=1, maximum_members=4)
        tc.validate_team_size(1)  # no raise

    def test_teams_disabled_rejects_more_than_one(self) -> None:
        tc = TeamConfiguration(enabled=False, minimum_members=1, maximum_members=4)
        with pytest.raises(ValueError, match="Teams are disabled"):
            tc.validate_team_size(2)

    def test_teams_enabled_accepts_within_range(self) -> None:
        tc = TeamConfiguration(enabled=True, minimum_members=2, maximum_members=4)
        tc.validate_team_size(2)
        tc.validate_team_size(3)
        tc.validate_team_size(4)

    def test_teams_enabled_below_minimum_raises(self) -> None:
        tc = TeamConfiguration(enabled=True, minimum_members=2, maximum_members=4)
        with pytest.raises(ValueError, match="below minimum"):
            tc.validate_team_size(1)

    def test_teams_enabled_above_maximum_raises(self) -> None:
        tc = TeamConfiguration(enabled=True, minimum_members=2, maximum_members=4)
        with pytest.raises(ValueError, match="exceeds maximum"):
            tc.validate_team_size(5)


class TestDeploymentConstraints:
    """Model validation."""

    def test_valid_constraints(self) -> None:
        c = DeploymentConstraints(
            maximum_concurrent_deployments=1000,
            auto_expire_minutes=120,
            team_configuration=TeamConfiguration(
                enabled=False,
                minimum_members=1,
                maximum_members=4,
            ),
        )
        assert c.maximum_concurrent_deployments == 1000
        assert c.auto_expire_minutes == 120


class TestGetDeploymentConstraints:
    """Load from config."""

    def test_returns_constraints_from_settings(self) -> None:
        with patch("app.core.config.get_settings") as gs:
            gs.return_value.MAXIMUM_CONCURRENT_DEPLOYMENTS = 500
            gs.return_value.AUTO_EXPIRE_MINUTES = 60
            gs.return_value.TEAM_CONFIGURATION_ENABLED = True
            gs.return_value.TEAM_MINIMUM_MEMBERS = 2
            gs.return_value.TEAM_MAXIMUM_MEMBERS = 8
            c = get_deployment_constraints()
        assert c.maximum_concurrent_deployments == 500
        assert c.auto_expire_minutes == 60
        assert c.team_configuration.enabled is True
        assert c.team_configuration.minimum_members == 2
        assert c.team_configuration.maximum_members == 8
