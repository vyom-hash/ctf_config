"""
Recipe Repository — data-access layer.

All queries use SQLAlchemy 2.0 async API.  Heavy-read paths use
`selectinload` / `joinedload` to eliminate N+1 problems.

Key patterns
────────────
• `selectinload`  → preferred for collections (issues one IN query per level)
• `joinedload`    → preferred for scalar relationships (one JOIN)
• All writes go through the session passed in; callers own the transaction.
"""
from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.recipe import (
    Recipe,
    RecipeAccessGateway,
    RecipeApproval,
    RecipeAutomationProfile,
    RecipeChallenge,
    RecipeChallengeHint,
    RecipeChallengeUnitLink,
    RecipeDnsResolver,
    RecipeDomainRoutingRule,
    RecipeDraft,
    RecipeGatewayExposureRule,
    RecipeNetworkDomain,
    RecipeNetworkProfile,
    RecipeScoringRules,
    RecipeVersion,
    RecipeVersionSnapshot,
    RecipeWorkloadUnit,
)


class RecipeRepository:
    """All DB operations for the recipe creation flow."""

    # ─────────────────────────── Draft ───────────────────────────────────────

    async def create_draft(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        name: str,
        description: Optional[str],
        category: Optional[str],
        created_by: Optional[uuid.UUID],
    ) -> Recipe:
        """
        Create a `recipe_drafts` row and the corresponding `recipes` row sharing
        the same UUID (required by FK constraints on recipe_versions and recipe_approvals).
        """
        draft = RecipeDraft(
            id=recipe_id,
            name=name,
            description=description,
            category=category,
            created_by=created_by,
        )
        session.add(draft)
        recipe = Recipe(
            id=recipe_id,
            name=name,
            description=description,
            category=category,
            created_by=created_by,
        )
        session.add(recipe)
        await session.flush()
        return recipe

    async def get_draft_by_id(
        self, session: AsyncSession, recipe_id: uuid.UUID
    ) -> Optional[Recipe]:
        result = await session.execute(
            select(Recipe).where(Recipe.id == recipe_id)
        )
        return result.scalar_one_or_none()

    async def list_drafts(
        self,
        session: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[Recipe], int]:
        """List recipe drafts with pagination. Returns (rows, total_count)."""
        count_stmt = select(func.count()).select_from(Recipe)
        total = (await session.execute(count_stmt)).scalar() or 0
        offset = (page - 1) * page_size
        stmt = (
            select(Recipe)
            .order_by(Recipe.updated_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return rows, total

    # ─────────────────────────── Network profile ──────────────────────────────

    async def upsert_network_profile(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        segmentation_strategy: str,
        default_subnet_mask: int,
        gateway_offset: int,
    ) -> RecipeNetworkProfile:
        """Replace the single network profile for this recipe."""
        await session.execute(
            delete(RecipeNetworkProfile).where(RecipeNetworkProfile.recipe_id == recipe_id)
        )
        profile = RecipeNetworkProfile(
            recipe_id=recipe_id,
            segmentation_strategy=segmentation_strategy,
            default_subnet_mask=default_subnet_mask,
            gateway_offset=gateway_offset,
        )
        session.add(profile)
        await session.flush()
        return profile

    async def replace_dns_resolvers(
        self, session: AsyncSession, *, recipe_id: uuid.UUID, addresses: list[str]
    ) -> list[RecipeDnsResolver]:
        await session.execute(
            delete(RecipeDnsResolver).where(RecipeDnsResolver.recipe_id == recipe_id)
        )
        resolvers = [
            RecipeDnsResolver(recipe_id=recipe_id, resolver_address=addr)
            for addr in addresses
        ]
        session.add_all(resolvers)
        await session.flush()
        return resolvers

    # ─────────────────────────── Domains ─────────────────────────────────────

    async def add_domain(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        domain_key: str,
        description: Optional[str],
        public_ingress_enabled: bool,
        allow_inter_domain_routing: bool = False,
    ) -> RecipeNetworkDomain:
        domain = RecipeNetworkDomain(
            recipe_id=recipe_id,
            domain_key=domain_key,
            description=description,
            public_ingress_enabled=public_ingress_enabled,
            allow_inter_domain_routing=allow_inter_domain_routing,
        )
        session.add(domain)
        await session.flush()
        return domain

    async def add_routing_rule(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        source_domain: str,
        destination_domain: str,
        routing_policy: str,
    ) -> RecipeDomainRoutingRule:
        rule = RecipeDomainRoutingRule(
            recipe_id=recipe_id,
            source_domain=source_domain,
            destination_domain=destination_domain,
            routing_policy=routing_policy,
        )
        session.add(rule)
        await session.flush()
        return rule

    # ─────────────────────────── Workload units ───────────────────────────────

    async def add_workload_unit(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        unit_key: str,
        functional_role: Optional[str],
        network_position_index: Optional[int],
        runtime_profile: Optional[str],
        resource_tier: Optional[str],
        assigned_domain: Optional[str],
        connectivity_profile: Optional[str],
        agent_enabled: bool,
        automation: Optional[dict] = None,
    ) -> RecipeWorkloadUnit:
        unit = RecipeWorkloadUnit(
            recipe_id=recipe_id,
            unit_key=unit_key,
            functional_role=functional_role,
            network_position_index=network_position_index,
            runtime_profile=runtime_profile,
            resource_tier=resource_tier,
            assigned_domain=assigned_domain,
            connectivity_profile=connectivity_profile,
            agent_enabled=agent_enabled,
        )
        session.add(unit)
        await session.flush()

        if automation:
            ap = RecipeAutomationProfile(
                workload_unit_id=unit.id,
                bootstrap_reference=automation.get("bootstrap_reference"),
                initialization_reference=automation.get("initialization_reference"),
                health_check_reference=automation.get("health_check_reference"),
            )
            session.add(ap)
            await session.flush()

        return unit

    # ─────────────────────────── Challenges ──────────────────────────────────

    async def add_challenge(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        challenge_key: str,
        title: Optional[str],
        category: Optional[str],
        flag_validation_type: Optional[str],
        difficulty: Optional[str],
        base_score: Optional[int],
        flag_pattern: Optional[str],
        experience_mode: Optional[str],
        sub_category: Optional[str],
        isolation_strategy: Optional[str],
        linked_unit_ids: list[uuid.UUID],
        hints: list[dict],
    ) -> RecipeChallenge:
        challenge = RecipeChallenge(
            recipe_id=recipe_id,
            challenge_key=challenge_key,
            title=title,
            category=category,
            flag_validation_type=flag_validation_type,
            difficulty=difficulty,
            base_score=base_score,
            flag_pattern=flag_pattern,
            experience_mode=experience_mode,
            sub_category=sub_category,
            isolation_strategy=isolation_strategy,
        )
        session.add(challenge)
        await session.flush()

        for unit_id in linked_unit_ids:
            session.add(RecipeChallengeUnitLink(challenge_id=challenge.id, unit_id=unit_id))

        for idx, hint in enumerate(hints):
            session.add(
                RecipeChallengeHint(
                    challenge_id=challenge.id,
                    hint_text=hint.get("hint_text"),
                    penalty_points=hint.get("penalty_points"),
                    display_order=hint.get("display_order", idx),
                )
            )

        await session.flush()
        return challenge

    # ─────────────────────────── Gateways ────────────────────────────────────

    async def add_gateway(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        gateway_key: str,
        gateway_type: Optional[str],
        runtime_profile: Optional[str],
        resource_tier: Optional[str],
        is_active: bool,
        exposure_rules: list[dict],
    ) -> RecipeAccessGateway:
        gateway = RecipeAccessGateway(
            recipe_id=recipe_id,
            gateway_key=gateway_key,
            gateway_type=gateway_type,
            runtime_profile=runtime_profile,
            resource_tier=resource_tier,
            is_active=is_active,
        )
        session.add(gateway)
        await session.flush()

        for rule in exposure_rules:
            session.add(
                RecipeGatewayExposureRule(
                    gateway_id=gateway.id,
                    unit_key=rule.get("unit_key"),
                    internal_port=rule.get("internal_port"),
                    transport_protocol=rule.get("transport_protocol"),
                )
            )

        await session.flush()
        return gateway

    # ─────────────────────────── Scoring rules ───────────────────────────────

    async def upsert_scoring_rules(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        dynamic_scoring: bool,
        minimum_score_floor: Optional[int],
        decay_strategy: Optional[str],
    ) -> RecipeScoringRules:
        await session.execute(
            delete(RecipeScoringRules).where(RecipeScoringRules.recipe_id == recipe_id)
        )
        rules = RecipeScoringRules(
            recipe_id=recipe_id,
            dynamic_scoring=dynamic_scoring,
            minimum_score_floor=minimum_score_floor,
            decay_strategy=decay_strategy,
        )
        session.add(rules)
        await session.flush()
        return rules

    # ─────────────────────────── Full eager load ─────────────────────────────

    async def get_full_recipe(
        self, session: AsyncSession, recipe_id: uuid.UUID
    ) -> Optional[Recipe]:
        """
        Load a `Recipe` with ALL child collections in **3 SQL queries**
        (one per selectinload level) — no N+1 risk.

        Query plan:
          Q1  SELECT recipes WHERE id = ?
          Q2  SELECT * FROM recipe_network_profiles/domains/routing_rules/dns_resolvers/scoring
              WHERE recipe_id IN (?)                        ← selectinload batch
          Q3  SELECT * FROM workload_units WHERE recipe_id IN (?)
              + automation_profiles WHERE workload_unit_id IN (?)
              + challenge_unit_links + challenges + hints + gateways + exposure_rules
        """
        stmt = (
            select(Recipe)
            .where(Recipe.id == recipe_id)
            .options(
                selectinload(Recipe.network_profiles),
                selectinload(Recipe.network_domains),
                selectinload(Recipe.domain_routing_rules),
                selectinload(Recipe.dns_resolvers),
                selectinload(Recipe.scoring_rules),
                selectinload(Recipe.workload_units).selectinload(
                    RecipeWorkloadUnit.automation_profile
                ),
                selectinload(Recipe.workload_units).selectinload(
                    RecipeWorkloadUnit.challenge_links
                ),
                selectinload(Recipe.challenges)
                .selectinload(RecipeChallenge.unit_links)
                .joinedload(RecipeChallengeUnitLink.unit),
                selectinload(Recipe.challenges).selectinload(RecipeChallenge.hints),
                selectinload(Recipe.access_gateways).selectinload(
                    RecipeAccessGateway.exposure_rules
                ),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ─────────────────────────── Version + snapshot ───────────────────────────

    async def get_next_version_number(
        self, session: AsyncSession, recipe_id: uuid.UUID
    ) -> int:
        result = await session.execute(
            select(RecipeVersion.version_number)
            .where(RecipeVersion.recipe_id == recipe_id)
            .order_by(RecipeVersion.version_number.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()
        return (last or 0) + 1

    async def create_version(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        version_number: int,
        checksum: str,
    ) -> RecipeVersion:
        version = RecipeVersion(
            recipe_id=recipe_id,
            version_number=version_number,
            checksum=checksum,
        )
        session.add(version)
        await session.flush()
        return version

    async def create_snapshot(
        self,
        session: AsyncSession,
        *,
        version_id: uuid.UUID,
        snapshot_json: dict,
    ) -> RecipeVersionSnapshot:
        snap = RecipeVersionSnapshot(version_id=version_id, snapshot_json=snapshot_json)
        session.add(snap)
        await session.flush()
        return snap

    async def get_snapshot_by_version_id(
        self, session: AsyncSession, version_id: uuid.UUID
    ) -> Optional[dict]:
        """Return the stored snapshot JSON for a given recipe version, if it exists."""
        result = await session.execute(
            select(RecipeVersionSnapshot.snapshot_json).where(
                RecipeVersionSnapshot.version_id == version_id
            )
        )
        return result.scalar_one_or_none()

    async def increment_recipe_version(
        self, session: AsyncSession, *, recipe_id: uuid.UUID, new_version: int
    ) -> None:
        await session.execute(
            update(Recipe)
            .where(Recipe.id == recipe_id)
            .values(version=new_version)
        )

    # ─────────────────────────── Challenge flag lookup ────────────────────────

    async def get_challenge_by_key(
        self, session: AsyncSession, *, recipe_id: uuid.UUID, challenge_key: str
    ) -> Optional[RecipeChallenge]:
        result = await session.execute(
            select(RecipeChallenge).where(
                RecipeChallenge.recipe_id == recipe_id,
                RecipeChallenge.challenge_key == challenge_key,
            )
        )
        return result.scalar_one_or_none()

    # ─────────────────────────── Approval workflow ────────────────────────────

    async def get_draft_by_id_with_approval(
        self, session: AsyncSession, recipe_id: uuid.UUID
    ) -> Optional[Recipe]:
        """Load recipe row (approval_status is a column on Recipe directly)."""
        result = await session.execute(
            select(Recipe).where(Recipe.id == recipe_id)
        )
        return result.scalar_one_or_none()

    async def update_draft_approval_status(
        self, session: AsyncSession, *, recipe_id: uuid.UUID, approval_status: str
    ) -> None:
        await session.execute(
            update(Recipe)
            .where(Recipe.id == recipe_id)
            .values(approval_status=approval_status)
        )

    async def create_approval_record(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        decision: str,
        comments: Optional[str],
    ) -> RecipeApproval:
        record = RecipeApproval(
            recipe_id=recipe_id,
            reviewer_id=reviewer_id,
            decision=decision,
            comments=comments,
        )
        session.add(record)
        await session.flush()
        return record

    # ─────────────────────────── Draft metadata update ───────────────────────

    async def update_draft_metadata(
        self,
        session: AsyncSession,
        *,
        recipe_id: uuid.UUID,
        updates: dict,
    ) -> None:
        """Apply a partial update to the recipe row."""
        if not updates:
            return
        await session.execute(
            update(Recipe).where(Recipe.id == recipe_id).values(**updates)
        )
        await session.flush()

    # ─────────────────────────── Domain GET / UPDATE ──────────────────────────

    async def get_domain_by_id(
        self, session: AsyncSession, domain_id: uuid.UUID
    ) -> Optional[RecipeNetworkDomain]:
        result = await session.execute(
            select(RecipeNetworkDomain).where(RecipeNetworkDomain.id == domain_id)
        )
        return result.scalar_one_or_none()

    async def update_domain(
        self,
        session: AsyncSession,
        *,
        domain: RecipeNetworkDomain,
        updates: dict,
    ) -> RecipeNetworkDomain:
        for key, value in updates.items():
            setattr(domain, key, value)
        await session.flush()
        return domain

    # ─────────────────────────── Workload unit GET / UPDATE ───────────────────

    async def get_unit_by_id(
        self, session: AsyncSession, unit_id: uuid.UUID
    ) -> Optional[RecipeWorkloadUnit]:
        result = await session.execute(
            select(RecipeWorkloadUnit)
            .where(RecipeWorkloadUnit.id == unit_id)
            .options(joinedload(RecipeWorkloadUnit.automation_profile))
        )
        return result.scalar_one_or_none()

    async def update_unit(
        self,
        session: AsyncSession,
        *,
        unit: RecipeWorkloadUnit,
        updates: dict,
        automation: Optional[dict],
    ) -> RecipeWorkloadUnit:
        scalar_updates = {k: v for k, v in updates.items() if k != "automation_profile"}
        for key, value in scalar_updates.items():
            setattr(unit, key, value)
        if automation is not None:
            if unit.automation_profile:
                for k, v in automation.items():
                    setattr(unit.automation_profile, k, v)
            else:
                session.add(RecipeAutomationProfile(workload_unit_id=unit.id, **automation))
        await session.flush()
        return unit

    # ─────────────────────────── Challenge GET / UPDATE ───────────────────────

    async def get_challenge_by_id(
        self, session: AsyncSession, challenge_id: uuid.UUID
    ) -> Optional[RecipeChallenge]:
        result = await session.execute(
            select(RecipeChallenge)
            .where(RecipeChallenge.id == challenge_id)
            .options(
                selectinload(RecipeChallenge.unit_links).joinedload(RecipeChallengeUnitLink.unit),
                selectinload(RecipeChallenge.hints),
            )
        )
        return result.scalar_one_or_none()

    async def update_challenge(
        self,
        session: AsyncSession,
        *,
        challenge: RecipeChallenge,
        updates: dict,
        linked_unit_ids: Optional[list],
        hints: Optional[list],
    ) -> RecipeChallenge:
        scalar_updates = {k: v for k, v in updates.items() if k not in ("linked_unit_ids", "hints")}
        for key, value in scalar_updates.items():
            setattr(challenge, key, value)
        if linked_unit_ids is not None:
            await session.execute(
                delete(RecipeChallengeUnitLink).where(
                    RecipeChallengeUnitLink.challenge_id == challenge.id
                )
            )
            for uid in linked_unit_ids:
                session.add(RecipeChallengeUnitLink(challenge_id=challenge.id, unit_id=uid))
        if hints is not None:
            await session.execute(
                delete(RecipeChallengeHint).where(
                    RecipeChallengeHint.challenge_id == challenge.id
                )
            )
            for idx, hint in enumerate(hints):
                session.add(
                    RecipeChallengeHint(
                        challenge_id=challenge.id,
                        hint_text=hint.get("hint_text"),
                        penalty_points=hint.get("penalty_points"),
                        display_order=hint.get("display_order", idx),
                    )
                )
        await session.flush()
        return await self.get_challenge_by_id(session, challenge.id)

    # ─────────────────────────── Gateway GET / UPDATE ─────────────────────────

    async def get_gateway_by_id(
        self, session: AsyncSession, gateway_id: uuid.UUID
    ) -> Optional[RecipeAccessGateway]:
        result = await session.execute(
            select(RecipeAccessGateway)
            .where(RecipeAccessGateway.id == gateway_id)
            .options(selectinload(RecipeAccessGateway.exposure_rules))
        )
        return result.scalar_one_or_none()

    async def update_gateway(
        self,
        session: AsyncSession,
        *,
        gateway: RecipeAccessGateway,
        updates: dict,
        exposure_rules: Optional[list],
    ) -> RecipeAccessGateway:
        scalar_updates = {k: v for k, v in updates.items() if k != "exposure_rules"}
        for key, value in scalar_updates.items():
            setattr(gateway, key, value)
        if exposure_rules is not None:
            await session.execute(
                delete(RecipeGatewayExposureRule).where(
                    RecipeGatewayExposureRule.gateway_id == gateway.id
                )
            )
            for rule in exposure_rules:
                session.add(
                    RecipeGatewayExposureRule(
                        gateway_id=gateway.id,
                        unit_key=rule.get("unit_key"),
                        internal_port=rule.get("internal_port"),
                        transport_protocol=rule.get("transport_protocol"),
                    )
                )
        await session.flush()
        return await self.get_gateway_by_id(session, gateway.id)

    # ─────────────────────────── Version lookup (for deployment validation) ───

    async def get_version_by_id(
        self, session: AsyncSession, version_id: uuid.UUID
    ) -> Optional[RecipeVersion]:
        result = await session.execute(
            select(RecipeVersion).where(RecipeVersion.id == version_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_approved_version(
        self, session: AsyncSession, recipe_id: uuid.UUID
    ) -> Optional[RecipeVersion]:
        """Latest recipe version for recipe that is published and approved (for deployment)."""
        from app.models.recipe import ApprovalStatus

        result = await session.execute(
            select(RecipeVersion)
            .where(
                RecipeVersion.recipe_id == recipe_id,
                RecipeVersion.is_published.is_(True),
                RecipeVersion.approval_status == ApprovalStatus.APPROVED,
            )
            .order_by(RecipeVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_version_by_draft_and_number(
        self,
        session: AsyncSession,
        recipe_id: uuid.UUID,
        version_number: int,
    ) -> Optional[RecipeVersion]:
        """Get recipe version by recipe_id and version_number (for deployment from-draft)."""
        result = await session.execute(
            select(RecipeVersion).where(
                RecipeVersion.recipe_id == recipe_id,
                RecipeVersion.version_number == version_number,
            )
        )
        return result.scalar_one_or_none()

    async def get_version_ids_by_draft_id(
        self, session: AsyncSession, recipe_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Return all recipe version IDs for the given recipe (for deployment conflict check)."""
        result = await session.execute(
            select(RecipeVersion.id).where(RecipeVersion.recipe_id == recipe_id)
        )
        return [row[0] for row in result.all()]

    async def delete_draft(
        self, session: AsyncSession, recipe_id: uuid.UUID
    ) -> bool:
        """
        Delete a recipe and all children.
        Caller must ensure no deployments reference any version of this recipe.
        Order: snapshots -> versions -> recipe.
        """
        # Delete snapshots for all versions of this recipe
        subq = select(RecipeVersion.id).where(RecipeVersion.recipe_id == recipe_id)
        await session.execute(
            delete(RecipeVersionSnapshot).where(
                RecipeVersionSnapshot.version_id.in_(subq)
            )
        )
        await session.execute(delete(RecipeVersion).where(RecipeVersion.recipe_id == recipe_id))
        await session.execute(delete(Recipe).where(Recipe.id == recipe_id))
        await session.flush()
        return True

    async def delete_domain_by_id(
        self, session: AsyncSession, recipe_id: uuid.UUID, domain_id: uuid.UUID
    ) -> bool:
        """Delete a network domain by id scoped to recipe. Returns True if deleted."""
        stmt = delete(RecipeNetworkDomain).where(
            RecipeNetworkDomain.id == domain_id,
            RecipeNetworkDomain.recipe_id == recipe_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0

    async def delete_unit_by_id(
        self, session: AsyncSession, recipe_id: uuid.UUID, unit_id: uuid.UUID
    ) -> bool:
        """Delete a workload unit by id scoped to recipe (cascade automation, challenge_links). Returns True if deleted."""
        stmt = delete(RecipeWorkloadUnit).where(
            RecipeWorkloadUnit.id == unit_id,
            RecipeWorkloadUnit.recipe_id == recipe_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0

    async def delete_challenge_by_id(
        self, session: AsyncSession, recipe_id: uuid.UUID, challenge_id: uuid.UUID
    ) -> bool:
        """Delete a challenge by id scoped to recipe (cascade hints, unit_links). Returns True if deleted."""
        stmt = delete(RecipeChallenge).where(
            RecipeChallenge.id == challenge_id,
            RecipeChallenge.recipe_id == recipe_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0

    async def delete_gateway_by_id(
        self, session: AsyncSession, recipe_id: uuid.UUID, gateway_id: uuid.UUID
    ) -> bool:
        """Delete a gateway by id scoped to recipe (cascade exposure_rules). Returns True if deleted."""
        stmt = delete(RecipeAccessGateway).where(
            RecipeAccessGateway.id == gateway_id,
            RecipeAccessGateway.recipe_id == recipe_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0
