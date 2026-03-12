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
    from app.api.schemas.challenge import ChallengeWithRecipeResponse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer


# ─────────────────────────────── Base ────────────────────────────────────────

class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ─────────────────────────────── Draft ───────────────────────────────────────

class DraftCreate(_Base):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)


class DraftUpdate(_Base):
    """Partial update for draft metadata."""
    name: Optional[str] = Field(None, max_length=255)
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
    items: List[RecipeListItem] = Field(default_factory=list)
    next_page_token: Optional[str] = Field(None)
    total_size: Optional[int] = Field(None)


# ─────────────────────────────── Global domain (replaces NetworkProfile) ─────

class GlobalDomainConfig(_Base):
    """DNS resolvers and gateway offset — replaces the old network profile."""
    dns_resolvers: List[str] = Field(default_factory=list)
    gw_offset: int = Field(..., ge=1)


class GlobalDomainResponse(_Base):
    id: uuid.UUID
    recipe_id: uuid.UUID
    gw_offset: int
    dns: List[str] = Field(default_factory=list)


# ─────────────────────────────── Domain ──────────────────────────────────────

class DomainCreate(_Base):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    enable_egress: bool = False


class DomainResponse(_Base):
    id: uuid.UUID
    recipe_id: uuid.UUID
    name: str
    desc: Optional[str] = None
    enable_egress: bool
    domain_size: Optional[int] = None

    @classmethod
    def from_orm_domain(cls, d: Any) -> "DomainResponse":
        return cls(
            id=d.id,
            recipe_id=d.recipe_id,
            name=d.name,
            desc=d.description,
            enable_egress=d.enable_egress,
            domain_size=d.domain_size,
        )


class DomainUpdate(_Base):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    enable_egress: Optional[bool] = None


# ─────────────────────────────── Workload unit ───────────────────────────────

class AutomationProfileCreate(_Base):
    bootstrap_automation: Optional[str] = None
    preflight_automation: Optional[str] = None
    heartbeat_automation: Optional[str] = None


class WorkloadUnitCreate(_Base):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    allocation_index: Optional[int] = Field(None, ge=0)
    runtime_profile: Optional[str] = Field(None, max_length=150)
    resource_tier: Optional[str] = Field(None, max_length=100)
    assigned_domain: Optional[str] = Field(None, max_length=100)
    access_method: Optional[str] = Field(None, max_length=100)
    unit_control_active: bool = False
    automation_profile: Optional[AutomationProfileCreate] = None


class WorkloadUnitResponse(_Base):
    id: uuid.UUID
    recipe_id: uuid.UUID
    name: str
    description: Optional[str]
    allocation_index: Optional[int]
    runtime_profile: Optional[str]
    resource_tier: Optional[str]
    assigned_domain: Optional[str]
    access_method: Optional[str]
    unit_control_active: bool
    automation_profile: Optional[AutomationProfileCreate]


class WorkloadUnitUpdate(_Base):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    allocation_index: Optional[int] = Field(None, ge=0)
    runtime_profile: Optional[str] = Field(None, max_length=150)
    resource_tier: Optional[str] = Field(None, max_length=100)
    assigned_domain: Optional[str] = Field(None, max_length=100)
    access_method: Optional[str] = Field(None, max_length=100)
    unit_control_active: Optional[bool] = None
    automation_profile: Optional[AutomationProfileCreate] = None


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
    type: Optional[str] = Field(None, pattern=r"^(jeopardy|guided)$")
    sub_category: Optional[str] = Field(None, pattern=r"^(selfpaced|event)$")
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


class ChallengeUpdate(_Base):
    challenge_key: Optional[str] = Field(None, max_length=100)
    title: Optional[str] = Field(None, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    flag_validation_type: Optional[str] = Field(None, max_length=50)
    difficulty: Optional[str] = Field(None, pattern=r"^(easy|medium|hard|expert)$")
    base_score: Optional[int] = Field(None, ge=0)
    flag_pattern: Optional[str] = None
    type: Optional[str] = Field(None, pattern=r"^(jeopardy|guided)$")
    linked_unit_ids: Optional[List[uuid.UUID]] = None
    hints: Optional[List[ChallengeHintCreate]] = None


# ─────────────────────────────── Gateway ─────────────────────────────────────

class IngressPolicyCreate(_Base):
    """Inbound port forwarding rule (replaces ExposureRule)."""
    name: Optional[str] = Field(None, max_length=100)
    desc: Optional[str] = None
    wl_unit: str = Field(..., max_length=100)
    int_port: int = Field(..., ge=1, le=65535)
    proto: str = Field(..., pattern=r"^(tcp|udp|sctp)$")
    ext_port: Optional[int] = Field(None, ge=1, le=65535)


class GatewayCreate(_Base):
    gateway_key: str = Field(..., max_length=100)
    gateway_type: Optional[str] = Field(
        None, pattern=r"^(vyos|pfsense)$"
    )
    runtime_profile: Optional[str] = Field(None, max_length=150)
    resource_tier: Optional[str] = Field(None, max_length=100)
    is_active: bool = True
    secure_shell: bool = False
    egress_ip: bool = False
    ingress_policies: List[IngressPolicyCreate] = Field(default_factory=list)


class IngressPolicyResponse(_Base):
    id: uuid.UUID
    name: Optional[str]
    desc: Optional[str]
    wl_unit: Optional[str]
    int_port: Optional[int]
    proto: Optional[str]
    ext_port: Optional[int]

    @classmethod
    def from_orm_rule(cls, r: Any) -> "IngressPolicyResponse":
        return cls(
            id=r.id,
            name=r.rule_name,
            desc=r.rule_desc,
            wl_unit=r.wl_unit,
            int_port=r.int_port,
            proto=r.proto,
            ext_port=r.ext_port,
        )


class GatewayResponse(_Base):
    id: uuid.UUID
    recipe_id: uuid.UUID
    gateway_key: str
    gateway_type: Optional[str]
    runtime_profile: Optional[str]
    resource_tier: Optional[str]
    is_active: bool
    secure_shell: bool
    egress_ip: bool
    ingress_policies: List[IngressPolicyResponse]


class GatewayUpdate(_Base):
    gateway_key: Optional[str] = Field(None, max_length=100)
    gateway_type: Optional[str] = Field(None, pattern=r"^(vyos|pfsense)$")
    runtime_profile: Optional[str] = Field(None, max_length=150)
    resource_tier: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None
    secure_shell: Optional[bool] = None
    egress_ip: Optional[bool] = None
    ingress_policies: Optional[List[IngressPolicyCreate]] = None


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


# ─────────────────────────────── Draft detail (full GET response) ─────────────

class DraftDetailResponse(_Base):
    recipe_id: uuid.UUID
    name: Optional[str]
    description: Optional[str]
    category: Optional[str]
    enable_jumphost: bool = True
    approval_status: str
    global_domain: Optional[GlobalDomainResponse] = None
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
        if data.get("global_domain"):
            _strip(data["global_domain"])
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
    global_domain: Optional[dict[str, Any]] = None
    network_domains: List[dict[str, Any]] = Field(default_factory=list)
    domain_routing_rules: List[dict[str, Any]] = Field(default_factory=list)
    workload_units: List[dict[str, Any]] = Field(default_factory=list)
    access_gateways: List[dict[str, Any]] = Field(default_factory=list)
    access_box: Optional[dict[str, Any]] = None


# ─────────────────────────────── Published recipe (immutable version) ─────────

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


class PublishedGlobalDomain(_Base):
    """Global domain config — dns resolvers + gateway offset."""
    dns: List[str] = Field(default_factory=list)
    gw_offset: int


class PublishedAutomationProfile(_Base):
    bootstrap_automation: Optional[str] = None
    preflight_automation: Optional[str] = None
    heartbeat_automation: Optional[str] = None

    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: Any) -> dict:
        return {k: v for k, v in handler(self).items() if v is not None}


class PublishedDomain(_Base):
    id: uuid.UUID
    name: str
    desc: Optional[str] = None
    enable_egress: bool
    domain_size: Optional[int] = None

    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: Any) -> dict:
        return {k: v for k, v in handler(self).items() if v is not None}


class PublishedWorkloadUnit(_Base):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    allocation_index: Optional[int] = None
    runtime_profile: Optional[str] = None
    resource_tier: Optional[str] = None
    assigned_domain: Optional[str] = None
    access_method: Optional[str] = None
    unit_control_active: bool
    automations: Optional[PublishedAutomationProfile] = None

    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: Any) -> dict:
        return {k: v for k, v in handler(self).items() if v is not None}


class PublishedIngressPolicy(_Base):
    """Ingress policy using unit_id (UUID) for immutable reference."""
    unit_id: uuid.UUID
    name: Optional[str] = None
    proto: Optional[str] = None
    desc: Optional[str] = None
    ext_port: Optional[int] = None
    int_port: Optional[int] = None


class PublishedGateway(_Base):
    id: uuid.UUID
    secure_shell: bool
    runtime_profile: Optional[str] = None
    resource_tier: Optional[str] = None
    egress_ip: bool
    ingress_policies: List[PublishedIngressPolicy] = Field(default_factory=list)


class JumphostUnitInput(_Base):
    """Input schema for PUT /recipes/{id}/jumphost."""
    enable: bool = True
    allow_vnc: bool = True
    resource_tier: str = Field(..., max_length=50)
    assigned_domain: str = Field(..., max_length=255)
    runtime_profile: str = Field(..., max_length=255)
    egress_ip: bool = False
    allocation_index: int = Field(..., ge=0)


class PublishedAccessBox(_Base):
    """Access box (jumphost) config for deployment engine."""
    enable: bool = True
    domain: str
    runtime_profile: str
    resource_tier: str
    allocation_index: int
    egress_ip: bool = False
    allow_vnc: bool = True


class PublishedRecipeResponse(_Base):
    """
    Immutable snapshot of an approved recipe at the moment of publication.

    Stored verbatim in recipe_version_snapshots.snapshot_json.
    """
    recipe_version_id: uuid.UUID
    version_number: int
    published_at: str
    checksum: str
    status: str = "published"
    metadata: RecipeMetadata
    global_domain: Optional[PublishedGlobalDomain] = None
    domains: List[PublishedDomain] = Field(default_factory=list)
    workload_units: List[PublishedWorkloadUnit] = Field(default_factory=list)
    gateways: List[PublishedGateway] = Field(default_factory=list)
    access_box: Optional[PublishedAccessBox] = None


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
    approval_status: str
    message: str


class ReviewRequest(_Base):
    decision: str = Field(..., pattern=r"^(approved|rejected)$")
    comments: Optional[str] = None


class ReviewResponse(_Base):
    recipe_id: uuid.UUID
    reviewer_id: uuid.UUID
    decision: str
    approval_status: str
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
    message: str = "Version approved and ready for deployment"
