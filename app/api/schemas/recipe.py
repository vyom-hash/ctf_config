"""
Pydantic v2 request / response schemas for the Recipe Creation Flow.

Naming convention
─────────────────
  *Create   → inbound payloads (POST/PUT body)
  *Response → outbound representations
  *Config   → idempotent upsert payloads (PUT body)
  Published*→ immutable published-version schemas (no nulls, resolved IDs)
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from app.api.schemas.exercise_instance import ExerciseWithRecipeResponse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer


# ─────────────────────────────── Base ────────────────────────────────────────

class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ─────────────────────────────── Draft ───────────────────────────────────────

class DraftCreate(_Base):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)


class DraftResponse(_Base):
    recipe_id: uuid.UUID
    status: str = "draft_created"
    approval_status: str = "DRAFT"


class RecipeListItem(_Base):
    """Minimal recipe/draft representation for list endpoints."""
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    approval_status: str = "DRAFT"
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None


class ListRecipesResponse(_Base):
    """Paginated list of recipes (drafts). Aligns with Google-style list responses."""
    items: List[RecipeListItem] = Field(default_factory=list, description="Recipe items for this page")
    next_page_token: Optional[str] = Field(None, description="Opaque token for next page; absent if no more results")
    total_size: Optional[int] = Field(None, description="Total number of items across all pages")

class NetworkProfileConfig(_Base):
    segmentation_strategy: str = Field(..., pattern=r"^(single_net|multi_net)$")
    default_subnet_mask: int = Field(..., ge=8, le=30)
    gateway_offset: int = Field(..., ge=1)
    dns_resolvers: List[str] = Field(default_factory=list)


class NetworkProfileResponse(_Base):
    id: uuid.UUID
    recipe_id: uuid.UUID
    segmentation_strategy: str
    default_subnet_mask: int
    gateway_offset: int
    dns_resolvers: List[str]


# ─────────────────────────────── Domain ──────────────────────────────────────

class DomainCreate(_Base):
    domain_key: str = Field(..., max_length=100)
    description: Optional[str] = None
    public_ingress_enabled: bool = False


class DomainRoutingRuleCreate(_Base):
    source_domain: str = Field(..., max_length=100)
    destination_domain: str = Field(..., max_length=100)
    routing_policy: str = Field(..., pattern=r"^(allow|deny|restricted)$")


class DomainResponse(_Base):
    id: uuid.UUID
    recipe_id: uuid.UUID
    domain_key: str
    description: Optional[str]
    public_ingress_enabled: bool


# ─────────────────────────────── Workload unit ───────────────────────────────

class AutomationProfileCreate(_Base):
    bootstrap_reference: Optional[str] = None
    initialization_reference: Optional[str] = None
    health_check_reference: Optional[str] = None


class WorkloadUnitCreate(_Base):
    unit_key: str = Field(..., max_length=100)
    functional_role: Optional[str] = Field(None, max_length=100)
    network_position_index: Optional[int] = Field(None, ge=0)
    runtime_profile: Optional[str] = Field(None, max_length=150)
    resource_tier: Optional[str] = Field(None, max_length=100)
    assigned_domain: Optional[str] = Field(None, max_length=100)
    connectivity_profile: Optional[str] = Field(None, max_length=100)
    agent_enabled: bool = False
    automation_profile: Optional[AutomationProfileCreate] = None


class WorkloadUnitResponse(_Base):
    id: uuid.UUID
    recipe_id: uuid.UUID
    unit_key: str
    functional_role: Optional[str]
    network_position_index: Optional[int]
    runtime_profile: Optional[str]
    resource_tier: Optional[str]
    assigned_domain: Optional[str]
    connectivity_profile: Optional[str]
    agent_enabled: bool
    automation_profile: Optional[AutomationProfileCreate]


# ─────────────────────────────── Challenge ───────────────────────────────────

class ChallengeHintCreate(_Base):
    hint_text: Optional[str] = None
    penalty_points: Optional[int] = Field(None, ge=0)
    display_order: Optional[int] = Field(None, ge=0)


class ChallengeCreate(_Base):
    challenge_key: str = Field(..., max_length=100)
    title: Optional[str] = Field(None, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    flag_validation_type: Optional[str] = Field(None, max_length=50)
    difficulty: Optional[str] = Field(None, pattern=r"^(easy|medium|hard|expert)$")
    base_score: Optional[int] = Field(None, ge=0)
    flag_pattern: Optional[str] = None
    # Draft-level experience metadata is now provided at challenge template creation time
    experience_mode: Optional[str] = Field(None, max_length=50)
    sub_category: Optional[str] = Field(None, pattern=r"^(jeopardy|guided)$")
    isolation_strategy: str = Field(..., pattern=r"^(per_user|per_team|shared)$")
    linked_unit_ids: List[uuid.UUID] = Field(default_factory=list)
    hints: List[ChallengeHintCreate] = Field(default_factory=list)


class ChallengeHintResponse(_Base):
    id: uuid.UUID
    hint_text: Optional[str]
    penalty_points: Optional[int]
    display_order: Optional[int]


class ChallengeResponse(_Base):
    id: uuid.UUID
    recipe_id: uuid.UUID
    challenge_key: Optional[str]
    title: Optional[str]
    category: Optional[str]
    flag_validation_type: Optional[str]
    difficulty: Optional[str]
    base_score: Optional[int]
    linked_unit_ids: List[uuid.UUID] = Field(default_factory=list)
    hints: List[ChallengeHintResponse] = Field(default_factory=list)


# ─────────────────────────────── Gateway ─────────────────────────────────────

class ExposureRuleCreate(_Base):
    unit_key: str = Field(..., max_length=100)
    internal_port: int = Field(..., ge=1, le=65535)
    transport_protocol: str = Field(..., pattern=r"^(tcp|udp|sctp)$")


class GatewayCreate(_Base):
    gateway_key: str = Field(..., max_length=100)
    gateway_type: Optional[str] = Field(
        None, pattern=r"^(vyos|pfsense)$", description="Gateway type: vyos or pfsense"
    )
    runtime_profile: Optional[str] = Field(None, max_length=150)
    resource_tier: Optional[str] = Field(None, max_length=100)
    is_active: bool = True
    exposure_rules: List[ExposureRuleCreate] = Field(default_factory=list)


class ExposureRuleResponse(_Base):
    id: uuid.UUID
    unit_key: Optional[str]
    internal_port: Optional[int]
    transport_protocol: Optional[str]


class GatewayResponse(_Base):
    id: uuid.UUID
    recipe_id: uuid.UUID
    gateway_key: str
    gateway_type: Optional[str]
    runtime_profile: Optional[str]
    resource_tier: Optional[str]
    is_active: bool
    exposure_rules: List[ExposureRuleResponse]


# ─────────────────────────────── Scoring ─────────────────────────────────────

class ScoringConfig(_Base):
    dynamic_scoring: bool = False
    minimum_score_floor: Optional[int] = Field(None, ge=0)
    decay_strategy: Optional[str] = Field(None, max_length=100)


class ScoringResponse(_Base):
    recipe_id: uuid.UUID
    dynamic_scoring: bool
    minimum_score_floor: Optional[int]
    decay_strategy: Optional[str]


# ─────────────────────────────── Update payloads (all fields optional) ────────

class DraftUpdate(_Base):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)


class DomainUpdate(_Base):
    domain_key: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    public_ingress_enabled: Optional[bool] = None


class WorkloadUnitUpdate(_Base):
    unit_key: Optional[str] = Field(None, max_length=100)
    functional_role: Optional[str] = Field(None, max_length=100)
    network_position_index: Optional[int] = Field(None, ge=0)
    runtime_profile: Optional[str] = Field(None, max_length=150)
    resource_tier: Optional[str] = Field(None, max_length=100)
    assigned_domain: Optional[str] = Field(None, max_length=100)
    connectivity_profile: Optional[str] = Field(None, max_length=100)
    agent_enabled: Optional[bool] = None
    automation_profile: Optional[AutomationProfileCreate] = None


class ChallengeUpdate(_Base):
    challenge_key: Optional[str] = Field(None, max_length=100)
    title: Optional[str] = Field(None, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    flag_validation_type: Optional[str] = Field(None, max_length=50)
    difficulty: Optional[str] = Field(None, pattern=r"^(easy|medium|hard|expert)$")
    base_score: Optional[int] = Field(None, ge=0)
    flag_pattern: Optional[str] = None
    linked_unit_ids: Optional[List[uuid.UUID]] = None
    hints: Optional[List[ChallengeHintCreate]] = None


class GatewayUpdate(_Base):
    gateway_key: Optional[str] = Field(None, max_length=100)
    gateway_type: Optional[str] = Field(
        None, pattern=r"^(vyos|pfsense)$", description="Gateway type: vyos or pfsense"
    )
    runtime_profile: Optional[str] = Field(None, max_length=150)
    resource_tier: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None
    exposure_rules: Optional[List[ExposureRuleCreate]] = None


# ─────────────────────────────── Draft detail (full GET response) ─────────────

class DraftDetailResponse(_Base):
    recipe_id: uuid.UUID
    name: Optional[str]
    description: Optional[str]
    category: Optional[str]
    enable_jumphost: bool = True
    approval_status: str
    network_profile: Optional[NetworkProfileResponse] = None
    domains: List[DomainResponse] = Field(default_factory=list)
    workload_units: List[WorkloadUnitResponse] = Field(default_factory=list)
    exercises: List[Any] = Field(
        default_factory=list,
        description="Exercise instances (superset) with embedded recipe details as subset",
    )
    gateways: List[GatewayResponse] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def _strip_nested_recipe_ids(self, handler: Any) -> dict:
        """Remove redundant recipe_id from nested infrastructure objects."""
        data: dict = handler(self)
        _strip = lambda obj: obj.pop("recipe_id", None) if isinstance(obj, dict) else None
        if data.get("network_profile"):
            _strip(data["network_profile"])
        for item in data.get("domains", []):
            _strip(item)
        for item in data.get("workload_units", []):
            _strip(item)
        for item in data.get("gateways", []):
            _strip(item)
        return data


# ─────────────────────────────── Validation ──────────────────────────────────

class ValidationError(_Base):
    field: str
    message: str


class ValidationResult(_Base):
    is_valid: bool
    errors: List[str] = Field(default_factory=list)


# ─────────────────────────────── Publish ─────────────────────────────────────

class PublishResponse(_Base):
    recipe_version_id: uuid.UUID
    version_number: int
    checksum: str
    status: str = "published"


# ─────────────────────────────── Blueprint (internal checksum payload) ────────

class BlueprintSnapshot(_Base):
    """Internal-only canonical payload used for SHA-256 checksum computation."""

    recipe_id: str
    name: str
    description: Optional[str]
    category: Optional[str]
    enable_jumphost: bool = True
    network_profile: Optional[dict[str, Any]] = None
    dns_resolvers: List[str] = Field(default_factory=list)
    network_domains: List[dict[str, Any]] = Field(default_factory=list)
    domain_routing_rules: List[dict[str, Any]] = Field(default_factory=list)
    workload_units: List[dict[str, Any]] = Field(default_factory=list)
    access_gateways: List[dict[str, Any]] = Field(default_factory=list)
    jumphost_unit: Optional[dict[str, Any]] = None


# ─────────────────────────────── Published recipe (immutable version) ─────────
#
# Returned by POST /drafts/{id}/publish and stored verbatim in
# recipe_version_snapshots.snapshot_json.
#
# Design rules enforced here:
#   • No recipe_id / draft_id redundancy — version identity lives at the top
#   • No null fields in workload units (stripped by serializers)
#   • Exposure rules use unit_id (UUID), not the mutable unit_key string
#   • Routing rules are embedded inside network_profile (not top-level)
# ──────────────────────────────────────────────────────────────────────────────

class RecipeMetadata(_Base):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    enable_jumphost: bool = True


class PublishedRoutingRule(_Base):
    source_domain: str
    destination_domain: str
    routing_policy: str = Field(..., pattern=r"^(allow|deny|restricted)$")


class PublishedNetworkProfile(_Base):
    segmentation_strategy: str
    default_subnet_mask: int
    gateway_offset: int
    dns_resolvers: List[str]
    routing_rules: List[PublishedRoutingRule] = Field(default_factory=list)


class PublishedAutomationProfile(_Base):
    bootstrap_reference: Optional[str] = None
    initialization_reference: Optional[str] = None
    health_check_reference: Optional[str] = None

    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: Any) -> dict:
        return {k: v for k, v in handler(self).items() if v is not None}


class PublishedDomain(_Base):
    id: uuid.UUID
    domain_key: str
    description: Optional[str] = None
    public_ingress_enabled: bool

    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: Any) -> dict:
        return {k: v for k, v in handler(self).items() if v is not None}


class PublishedWorkloadUnit(_Base):
    id: uuid.UUID
    unit_key: str
    functional_role: Optional[str] = None
    network_position_index: Optional[int] = None
    runtime_profile: Optional[str] = None
    resource_tier: Optional[str] = None
    assigned_domain: Optional[str] = None
    agent_enabled: bool
    automation_profile: Optional[PublishedAutomationProfile] = None

    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: Any) -> dict:
        return {k: v for k, v in handler(self).items() if v is not None}


class PublishedExposureRule(_Base):
    """Exposure rule using unit_id (UUID) instead of the mutable unit_key string."""
    unit_id: uuid.UUID
    internal_port: int
    transport_protocol: str


class PublishedGateway(_Base):
    id: uuid.UUID
    gateway_key: str
    gateway_type: str
    runtime_profile: Optional[str] = None
    resource_tier: Optional[str] = None
    exposure_rules: List[PublishedExposureRule]


class PublishedHint(_Base):
    id: uuid.UUID
    hint_text: str
    penalty_points: int
    display_order: int


class PublishedChallenge(_Base):
    id: uuid.UUID
    challenge_key: str
    title: str
    category: str
    difficulty: str
    flag_validation_type: str
    flag_pattern: Optional[str] = None   # exactly one of flag_pattern / flag_source must be set
    flag_source: Optional[str] = None    # e.g. "dynamic" — populated when flags are generated at runtime
    base_score: int
    linked_unit_ids: List[uuid.UUID]
    hints: List[PublishedHint] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: Any) -> dict:
        return {k: v for k, v in handler(self).items() if v is not None}


class PublishedScoringConfig(_Base):
    dynamic_scoring: bool
    minimum_score_floor: Optional[int] = None
    decay_strategy: Optional[str] = None

    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: Any) -> dict:
        return {k: v for k, v in handler(self).items() if v is not None}


class PublishedJumphostUnit(_Base):
    """
    Jumphost unit config included in the recipe JSON when enable_jumphost is True.
    Same shape as units for deployment engine consumption.
    """
    enabled: bool = True
    assigned_domain: str = Field(..., max_length=255)
    runtime_profile: str = Field(..., max_length=255)
    enable_vnc: bool = True
    network_position_index: int = Field(..., ge=0)
    resource_tier: str = Field(..., max_length=50)
    enable_floating_ip: bool = False


class PublishedRecipeResponse(_Base):
    """
    Immutable snapshot of an approved recipe at the moment of publication.

    Stored verbatim in recipe_version_snapshots.snapshot_json and returned
    by POST /drafts/{id}/publish.  Safe for deployment engine consumption.
    """
    recipe_version_id: uuid.UUID
    version_number: int
    published_at: str           # ISO 8601, e.g. "2025-08-01T12:00:00Z"
    checksum: str               # SHA-256 of BlueprintSnapshot canonical JSON
    status: str = "published"   # For clients / e2e (e.g. "published")
    metadata: RecipeMetadata
    network_profile: Optional[PublishedNetworkProfile] = None
    domains: List[PublishedDomain] = Field(default_factory=list)
    workload_units: List[PublishedWorkloadUnit] = Field(default_factory=list)
    gateways: List[PublishedGateway] = Field(default_factory=list)
    jumphost_unit: Optional[PublishedJumphostUnit] = None


# ─────────────────────────────── Flag submission (CTF runtime) ───────────────

class FlagSubmitRequest(_Base):
    flag: str = Field(..., min_length=1, max_length=512)


class FlagSubmitResponse(_Base):
    correct: bool
    message: str
    points_awarded: Optional[int] = None


# ─────────────────────────────── Leaderboard ─────────────────────────────────

class LeaderboardEntry(_Base):
    rank: int
    user_id: str
    score: float


class LeaderboardResponse(_Base):
    entries: List[LeaderboardEntry]
    total_participants: int


# ─────────────────────────────── Approval workflow ───────────────────────────

class SubmitForApprovalResponse(_Base):
    recipe_id: uuid.UUID
    approval_status: str        # PENDING_APPROVAL | APPROVED (when auto-approve on)
    message: str


class ReviewRequest(_Base):
    decision: str = Field(..., pattern=r"^(approved|rejected)$")
    comments: Optional[str] = None


class ReviewResponse(_Base):
    recipe_id: uuid.UUID
    reviewer_id: uuid.UUID
    decision: str
    approval_status: str        # APPROVED | REJECTED (updated draft status)
    comments: Optional[str]


# ─────────────────────────────── Deployment validation ───────────────────────

class DeploymentCreateRequest(_Base):
    recipe_version_id: uuid.UUID
    name: Optional[str] = Field(None, max_length=255)


class DeploymentValidateResponse(_Base):
    recipe_version_id: uuid.UUID
    version_number: int
    approval_status: str
    is_published: bool
    checksum: str
    message: str = "Version approved and ready for deployment"
