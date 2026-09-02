import logging
from typing import cast

from django.db import transaction
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.scoping.manager import resolve_effective_team_id

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.lazy_seed import seed_canonicals_tolerantly, sync_canonical_resolution
from products.review_hog.backend.reviewer.skill_loader import (
    CANONICAL_RESOLUTION_SKILL_NAMES,
    REVIEW_HOG_RESOLUTION_PREFIX,
    register_missing_resolution_config,
    visible_skill_names,
)
from products.skills.backend.models.skills import LLMSkill

logger = logging.getLogger(__name__)


class ReviewResolutionConfigSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        help_text="Name of the `review-hog-resolution-*` skill this row represents (the criteria's identity)."
    )
    active = serializers.BooleanField(
        help_text="Whether these criteria drive the resolution stage on the requesting user's PRs on this project."
    )
    description = serializers.CharField(
        allow_blank=True, help_text="The resolution skill's description, for display in the config UI."
    )
    body = serializers.CharField(
        allow_blank=True, help_text="The resolution skill's SKILL.md body, for the read-only skill viewer."
    )


class ReviewResolutionConfigSelectSerializer(serializers.Serializer):
    active = serializers.BooleanField(
        help_text=(
            "Set true to make these the single resolution criteria applied on the user's PRs. Only true "
            "is accepted — resolution criteria are single-active, so you switch by selecting a different "
            "skill, not by deactivating the current one."
        )
    )


class ReviewResolutionConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Per-user selection of ReviewHog's single active resolution-criteria skill for a project.

    A resolution skill is any team `review-hog-resolution-*` `LLMSkill` (canonical or custom —
    handled identically at run time): the bar the resolution stage applies to each unresolved
    review thread ("worth implementing" / "safe to implement unattended"). The skill itself is
    team-level; this surface only controls **which one** applies when the stage runs on the
    requesting user's PRs. Visibility is per-user: the menu shows the canonical plus the customs
    the requesting user authored — a teammate's custom is neither listed nor selectable
    (`visible_skill_names`). Like validators (and unlike perspectives), a run applies exactly one,
    so this is a single-active selection: `list` shows the visible skills with the user's active
    one flagged (the canonical auto-seeds active on first read); `partial_update` selects one by
    skill name, flipping the user's others off in the same call. There is always a default (the
    canonical), so no minimum floor is needed.
    """

    # llm_skill, not INTERNAL: responses carry skill body/description, so the llm_analytics RBAC
    # gate must apply — INTERNAL short-circuits AccessControlPermission before it checks anything.
    scope_object = "llm_skill"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewSkillConfig.objects.unscoped()
    serializer_class = ReviewResolutionConfigSerializer
    lookup_field = "skill_name"
    pagination_class = None

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ReviewResolutionConfigSerializer(many=True),
                description="Every resolution-criteria skill on this project, flagging the one active for the user.",
            ),
        },
        summary="List resolution criteria and which one is active",
        description=(
            "List the `review-hog-resolution-*` skills visible to the requesting user — the "
            "canonical criteria plus the customs they authored — flagging the one active for them. "
            "The canonical skill is auto-seeded active on the first read; a custom skill the user "
            "has not selected shows as inactive."
        ),
    )
    def list(self, request: Request, **kwargs) -> Response:
        # Resolve a raw environment URL id to its root team once — the skills and config rows all
        # live on the canonical team, so an unresolved id would render an empty menu.
        team_id = resolve_effective_team_id(self.team_id)
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        # A team that never ran a review has no LLMSkill rows yet — seed the canonical or the
        # menu renders empty until the first run.
        seed_canonicals_tolerantly(team_id, sync_canonical_resolution)
        register_missing_resolution_config(team_id, user_id)
        active_by_name = dict(
            ReviewSkillConfig.objects.for_team(team_id, canonical=True)
            .filter(user_id=user_id, skill_name__startswith=REVIEW_HOG_RESOLUTION_PREFIX)
            .values_list("skill_name", "enabled")
        )
        # Per-user visibility: the menu advertises the canonical plus this user's own customs —
        # never a teammate's.
        visible = visible_skill_names(
            team_id, user_id, prefix=REVIEW_HOG_RESOLUTION_PREFIX, canonical_names=CANONICAL_RESOLUTION_SKILL_NAMES
        )
        skills = LLMSkill.objects.filter(team_id=team_id, name__in=visible, is_latest=True, deleted=False).order_by(
            "name"
        )
        items = [
            {
                "skill_name": s.name,
                "active": active_by_name.get(s.name, False),
                "description": s.description,
                "body": s.body,
            }
            for s in skills
        ]
        return Response(ReviewResolutionConfigSerializer(items, many=True).data)

    @extend_schema(
        request=ReviewResolutionConfigSelectSerializer,
        responses={
            200: OpenApiResponse(
                response=ReviewResolutionConfigSerializer,
                description="The resolution criteria now active for the user.",
            ),
            400: OpenApiResponse(description="Not a resolution skill, or `active` was not true."),
            404: OpenApiResponse(description="No such resolution skill visible to the user on this project."),
        },
        summary="Select the active resolution criteria",
        description=(
            "Make a `review-hog-resolution-*` skill the single criteria the resolution stage applies "
            "on the requesting user's PRs, switching the user's other resolution skills off in the "
            "same call. Only skills visible to the user — the canonical plus the customs they "
            "authored — can be selected; anything else 404s. Upserts the per-user config row, so "
            "selecting a freshly authored custom skill works in one call."
        ),
    )
    def partial_update(self, request: Request, skill_name: str, **kwargs) -> Response:
        if not skill_name.startswith(REVIEW_HOG_RESOLUTION_PREFIX):
            raise ValidationError(f"'{skill_name}' is not a review resolution skill")
        # Resolve a raw environment URL id to its root team once: `for_team` canonicalizes its
        # filter but not the create kwargs, and mismatched ids mean a never-matching get plus
        # 500s on the unique constraint from the second call on.
        team_id = resolve_effective_team_id(self.team_id)
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        # Same cold-team seed as list(): selecting the canonical before the team's first review
        # would 404 without it.
        seed_canonicals_tolerantly(team_id, sync_canonical_resolution)
        skill = LLMSkill.objects.filter(team_id=team_id, name=skill_name, is_latest=True, deleted=False).first()
        # A teammate's custom 404s exactly like a missing skill — visibility is author-only, and a
        # distinct error would leak that the name exists.
        if skill is None or skill_name not in visible_skill_names(
            team_id, user_id, prefix=REVIEW_HOG_RESOLUTION_PREFIX, canonical_names=CANONICAL_RESOLUTION_SKILL_NAMES
        ):
            raise NotFound(f"No resolution skill '{skill_name}' on this project")

        select = ReviewResolutionConfigSelectSerializer(data=request.data)
        select.is_valid(raise_exception=True)
        if not select.validated_data["active"]:
            raise ValidationError(
                "Resolution criteria are single-active — select a different skill instead of deactivating"
            )

        register_missing_resolution_config(team_id, user_id)
        configs = ReviewSkillConfig.objects.for_team(team_id, canonical=True)
        # Single-active: deactivate-others + activate-this must land together, or a crash between them
        # leaves the user with no active skill (the loader's canonical fallback would heal it).
        with transaction.atomic():
            configs.filter(user_id=user_id, skill_name__startswith=REVIEW_HOG_RESOLUTION_PREFIX, enabled=True).exclude(
                skill_name=skill_name
            ).update(enabled=False, updated_at=timezone.now())
            # `team_id` / `user_id` stay in the create kwargs — the fail-closed filter doesn't propagate.
            config, _created = configs.get_or_create(
                team_id=team_id, user_id=user_id, skill_name=skill_name, defaults={"enabled": True}
            )
            if not config.enabled:
                config.enabled = True
                config.save(update_fields=["enabled", "updated_at"])
        return Response(
            ReviewResolutionConfigSerializer(
                {"skill_name": skill_name, "active": True, "description": skill.description, "body": skill.body}
            ).data
        )
