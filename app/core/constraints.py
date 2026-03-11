"""
Platform deployment constraints — used at deployment creation only.

Loaded from config (Settings). Recipe is never mutated.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TeamConfiguration(BaseModel):
    enabled: bool = False
    minimum_members: int = Field(..., ge=1, le=100)
    maximum_members: int = Field(..., ge=1, le=100)

    def validate_team_size(self, member_count: int) -> None:
        if not self.enabled:
            if member_count > 1:
                raise ValueError("Teams are disabled; only one member allowed")
            return
        if member_count < self.minimum_members:
            raise ValueError(
                f"Team size {member_count} is below minimum {self.minimum_members}"
            )
        if member_count > self.maximum_members:
            raise ValueError(
                f"Team size {member_count} exceeds maximum {self.maximum_members}"
            )


class DeploymentConstraints(BaseModel):
    maximum_concurrent_deployments: int = Field(..., ge=1, le=100_000)
    auto_expire_minutes: int = Field(..., ge=1, le=10080)  # max 7 days
    team_configuration: TeamConfiguration = Field(default_factory=TeamConfiguration)


def get_deployment_constraints() -> DeploymentConstraints:
    """Build constraints from app config (single source of truth)."""
    from app.core.config import get_settings
    s = get_settings()
    return DeploymentConstraints(
        maximum_concurrent_deployments=s.MAXIMUM_CONCURRENT_DEPLOYMENTS,
        auto_expire_minutes=s.AUTO_EXPIRE_MINUTES,
        team_configuration=TeamConfiguration(
            enabled=s.TEAM_CONFIGURATION_ENABLED,
            minimum_members=s.TEAM_MINIMUM_MEMBERS,
            maximum_members=s.TEAM_MAXIMUM_MEMBERS,
        ),
    )
