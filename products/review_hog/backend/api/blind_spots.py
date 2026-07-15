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
from products.review_hog.backend.reviewer.lazy_seed import seed_canonicals_tolerantly, sync_canonical_blind_spots
from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_BLIND_SPOTS_PREFIX,
    register_missing_blind_spots_config,
)
from products.skills.backend.models.skills import LLMSkill

logger = logging.getLogger(__name__)


class ReviewBlindSpotsConfigSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        help_text="Name of the `review-hog-blind-spots-*` skill this row represents (the sweep's identity)."
    )
    active = serializers.BooleanField(
        help_text="Whether this blind-spots skill runs the sweep on the requesting user's PR reviews on this project."
    )
    description = serializers.CharField(
        allow_blank=True, help_text="The blind-spots skill's description, for display in the config UI."
    )
    body = serializers.CharField(
        allow_blank=True, help_text="The blind-spots skill's SKILL.md body, for the read-only skill viewer."
    )


class ReviewBlindSpotsConfigSelectSerializer(serializers.Serializer):
    active = serializers.BooleanField(
        help_text=(
            "Set true to make this the single blind-spots skill that runs on the user's PR reviews. Only "
            "true is accepted — the blind-spot check is single-active, so you switch by selecting a "
            "different skill, not by deactivating the current one."
        )
    )


class ReviewBlindSpotsConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Per-user selection of ReviewHog's single active blind-spots skill for a project.

    A blind-spots skill is any team `review-hog-blind-spots-*` `LLMSkill` (canonical or custom —
    handled identically): the final per-chunk sweep that reads the perspective wave's findings and
    hunts for what every perspective missed. The skill itself is team-level; this surface only
    controls **which one** runs on the requesting user's PR reviews. Like validators (and unlike
    perspectives), a review runs exactly one, so this is a single-active selection: `list` shows
    every blind-spots skill with the user's active one flagged (the canonical auto-seeds active on
    first read); `partial_update` selects one by skill name, flipping the user's others off in the
    same call. There is always a default (the canonical), so no minimum floor is needed.
    """

    # llm_skill, not INTERNAL: responses carry skill body/description, so the llm_analytics RBAC
    # gate must apply — INTERNAL short-circuits AccessControlPermission before it checks anything.
    scope_object = "llm_skill"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewSkillConfig.objects.unscoped()
    serializer_class = ReviewBlindSpotsConfigSerializer
    lookup_field = "skill_name"
    pagination_class = None

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ReviewBlindSpotsConfigSerializer(many=True),
                description="Every blind-spots skill on this project, flagging the one active for the user.",
            ),
        },
        summary="List blind-spots skills and which one is active",
        description=(
            "List every `review-hog-blind-spots-*` skill on this project, flagging the one active for "
            "the requesting user. The canonical skill is auto-seeded active on the first read; a "
            "custom skill the user has not selected shows as inactive."
        ),
    )
    def list(self, request: Request, **kwargs) -> Response:
        # Resolve a raw environment URL id to its root team once — the skills and config rows all
        # live on the canonical team, so an unresolved id would render an empty menu.
        team_id = resolve_effective_team_id(self.team_id)
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        # A team that never ran a review has no LLMSkill rows yet — seed the canonical or the
        # menu renders empty until the first run.
        seed_canonicals_tolerantly(team_id, sync_canonical_blind_spots)
        register_missing_blind_spots_config(team_id, user_id)
        active_by_name = dict(
            ReviewSkillConfig.objects.for_team(team_id, canonical=True)
            .filter(user_id=user_id, skill_name__startswith=REVIEW_HOG_BLIND_SPOTS_PREFIX)
            .values_list("skill_name", "enabled")
        )
        skills = LLMSkill.objects.filter(
            team_id=team_id, name__startswith=REVIEW_HOG_BLIND_SPOTS_PREFIX, is_latest=True, deleted=False
        ).order_by("name")
        items = [
            {
                "skill_name": s.name,
                "active": active_by_name.get(s.name, False),
                "description": s.description,
                "body": s.body,
            }
            for s in skills
        ]
        return Response(ReviewBlindSpotsConfigSerializer(items, many=True).data)

    @extend_schema(
        request=ReviewBlindSpotsConfigSelectSerializer,
        responses={
            200: OpenApiResponse(
                response=ReviewBlindSpotsConfigSerializer,
                description="The blind-spots skill now active for the user.",
            ),
            400: OpenApiResponse(description="Not a blind-spots skill, or `active` was not true."),
            404: OpenApiResponse(description="No such blind-spots skill on this project."),
        },
        summary="Select the active blind-spots skill",
        description=(
            "Make a `review-hog-blind-spots-*` skill the single sweep that runs on the requesting "
            "user's PR reviews, switching the user's other blind-spots skills off in the same call. "
            "Upserts the per-user config row, so selecting a freshly authored custom skill works in "
            "one call."
        ),
    )
    def partial_update(self, request: Request, skill_name: str, **kwargs) -> Response:
        if not skill_name.startswith(REVIEW_HOG_BLIND_SPOTS_PREFIX):
            raise ValidationError(f"'{skill_name}' is not a review blind-spots skill")
        # Resolve a raw environment URL id to its root team once: `for_team` canonicalizes its
        # filter but not the create kwargs, and mismatched ids mean a never-matching get plus
        # 500s on the unique constraint from the second call on.
        team_id = resolve_effective_team_id(self.team_id)
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        # Same cold-team seed as list(): selecting the canonical before the team's first review
        # would 404 without it.
        seed_canonicals_tolerantly(team_id, sync_canonical_blind_spots)
        skill = LLMSkill.objects.filter(team_id=team_id, name=skill_name, is_latest=True, deleted=False).first()
        if skill is None:
            raise NotFound(f"No blind-spots skill '{skill_name}' on this project")

        select = ReviewBlindSpotsConfigSelectSerializer(data=request.data)
        select.is_valid(raise_exception=True)
        if not select.validated_data["active"]:
            raise ValidationError(
                "The blind-spot check is single-active — select a different skill instead of deactivating"
            )

        register_missing_blind_spots_config(team_id, user_id)
        configs = ReviewSkillConfig.objects.for_team(team_id, canonical=True)
        # Single-active: deactivate-others + activate-this must land together, or a crash between them
        # leaves the user with no active skill (the loader's canonical fallback would heal it).
        with transaction.atomic():
            configs.filter(user_id=user_id, skill_name__startswith=REVIEW_HOG_BLIND_SPOTS_PREFIX, enabled=True).exclude(
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
            ReviewBlindSpotsConfigSerializer(
                {"skill_name": skill_name, "active": True, "description": skill.description, "body": skill.body}
            ).data
        )
