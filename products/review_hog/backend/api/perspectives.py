import logging
from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.scoping.manager import resolve_effective_team_id

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_PERSPECTIVE_PREFIX,
    register_missing_perspective_configs,
)
from products.skills.backend.models.skills import LLMSkill

logger = logging.getLogger(__name__)


class ReviewPerspectiveConfigSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        help_text="Name of the `review-hog-perspective-*` skill this row toggles (the perspective's identity)."
    )
    enabled = serializers.BooleanField(
        help_text="Whether this perspective runs on the acting user's PR reviews on this project."
    )
    description = serializers.CharField(
        allow_blank=True, help_text="The perspective skill's description, for display in the config UI."
    )
    body = serializers.CharField(
        allow_blank=True, help_text="The perspective skill's SKILL.md body, for the read-only skill viewer."
    )


class ReviewPerspectiveConfigUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(
        help_text="Set true to run this perspective on the user's PR reviews, false to stop running it."
    )


class ReviewPerspectiveConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Per-user enablement of ReviewHog's review perspectives for a project.

    A perspective is any team `review-hog-perspective-*` `LLMSkill` (canonical or custom — handled
    identically). The skill itself is team-level; this surface only controls **which** perspectives
    run on the requesting user's PR reviews. `list` shows the full perspective menu joined with the
    user's enable state (the 3 canonicals auto-seed enabled on first read); `partial_update` toggles
    one by skill name (upserting the config row, so a freshly authored custom perspective is enabled
    by the same call). At least one perspective must stay enabled.
    """

    # llm_skill, not INTERNAL: responses carry skill body/description, so the llm_analytics RBAC
    # gate must apply — INTERNAL short-circuits AccessControlPermission before it checks anything.
    scope_object = "llm_skill"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewSkillConfig.objects.unscoped()
    serializer_class = ReviewPerspectiveConfigSerializer
    lookup_field = "skill_name"
    pagination_class = None

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ReviewPerspectiveConfigSerializer(many=True),
                description="Every review perspective on this project with the user's enable state, by skill name.",
            ),
        },
        summary="List review perspectives and their enablement",
        description=(
            "List every `review-hog-perspective-*` skill on this project joined with the requesting "
            "user's enable state. The 3 canonical perspectives are auto-seeded enabled on the first "
            "read; a custom perspective the user has not switched on shows as disabled."
        ),
    )
    def list(self, request: Request, **kwargs) -> Response:
        # Resolve a raw environment URL id to its root team once — the skills and config rows all
        # live on the canonical team, so an unresolved id would render an empty menu.
        team_id = resolve_effective_team_id(self.team_id)
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        register_missing_perspective_configs(team_id, user_id)
        # Prefix-scope: validators share this table, so only join perspective rows to the menu.
        enabled_by_name = dict(
            ReviewSkillConfig.objects.for_team(team_id, canonical=True)
            .filter(user_id=user_id, skill_name__startswith=REVIEW_HOG_PERSPECTIVE_PREFIX)
            .values_list("skill_name", "enabled")
        )
        skills = LLMSkill.objects.filter(
            team_id=team_id, name__startswith=REVIEW_HOG_PERSPECTIVE_PREFIX, is_latest=True, deleted=False
        ).order_by("name")
        items = [
            {
                "skill_name": s.name,
                "enabled": enabled_by_name.get(s.name, False),
                "description": s.description,
                "body": s.body,
            }
            for s in skills
        ]
        return Response(ReviewPerspectiveConfigSerializer(items, many=True).data)

    @extend_schema(
        request=ReviewPerspectiveConfigUpdateSerializer,
        responses={
            200: OpenApiResponse(
                response=ReviewPerspectiveConfigSerializer, description="The perspective's updated enable state."
            ),
            400: OpenApiResponse(description="Not a perspective skill, or disabling the user's last enabled one."),
            404: OpenApiResponse(description="No such perspective skill on this project."),
        },
        summary="Enable or disable a review perspective",
        description=(
            "Toggle whether a `review-hog-perspective-*` skill runs on the requesting user's PR "
            "reviews. Upserts the per-user config row, so enabling a freshly authored custom "
            "perspective works in one call. Rejected if it would leave the user with no enabled "
            "perspective."
        ),
    )
    def partial_update(self, request: Request, skill_name: str, **kwargs) -> Response:
        if not skill_name.startswith(REVIEW_HOG_PERSPECTIVE_PREFIX):
            raise ValidationError(f"'{skill_name}' is not a review perspective skill")
        # Resolve a raw environment URL id to its root team once: `for_team` canonicalizes its
        # filter but not the create kwargs, and mismatched ids mean a never-matching get plus
        # 500s on the unique constraint from the second call on.
        team_id = resolve_effective_team_id(self.team_id)
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        skill = LLMSkill.objects.filter(team_id=team_id, name=skill_name, is_latest=True, deleted=False).first()
        if skill is None:
            raise NotFound(f"No perspective skill '{skill_name}' on this project")

        update = ReviewPerspectiveConfigUpdateSerializer(data=request.data)
        update.is_valid(raise_exception=True)
        enabled: bool = update.validated_data["enabled"]

        # Seed the canonicals first so the min-1 floor counts a cold user's defaults, not zero.
        register_missing_perspective_configs(team_id, user_id)
        if not enabled:
            # Best-effort floor (count + write, no lock) — same as scouts. The loader's
            # NoEnabledPerspectivesError is the backstop if a rare concurrent double-disable slips through.
            # Prefix-scope: the floor counts only perspectives — an enabled validator (same table)
            # must not let a user disable their last perspective.
            others_enabled = (
                ReviewSkillConfig.objects.for_team(team_id, canonical=True)
                .filter(user_id=user_id, enabled=True, skill_name__startswith=REVIEW_HOG_PERSPECTIVE_PREFIX)
                .exclude(skill_name=skill_name)
                .count()
            )
            if others_enabled == 0:
                raise ValidationError("Cannot disable your last enabled perspective — at least one must stay on")

        # `team_id` / `user_id` stay in the create kwargs — the fail-closed filter doesn't propagate.
        config, _created = ReviewSkillConfig.objects.for_team(team_id, canonical=True).get_or_create(
            team_id=team_id, user_id=user_id, skill_name=skill_name, defaults={"enabled": enabled}
        )
        if config.enabled != enabled:
            config.enabled = enabled
            config.save(update_fields=["enabled", "updated_at"])
        return Response(
            ReviewPerspectiveConfigSerializer(
                {"skill_name": skill_name, "enabled": enabled, "description": skill.description, "body": skill.body}
            ).data
        )
