import logging
from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission

from products.review_hog.backend.facade.api import get_review_skill, list_review_skill_choices, select_review_skill
from products.review_hog.backend.facade.contracts import ReviewSkillNameError, ReviewSkillNotFoundError
from products.review_hog.backend.facade.enums import ReviewSkillKind

logger = logging.getLogger(__name__)


class ReviewResolutionConfigSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        help_text="Name of the `review-hog-resolution-*` skill this row represents (the criteria's identity)."
    )
    active = serializers.BooleanField(
        source="enabled",
        help_text="Whether these criteria drive the resolution stage on the requesting user's PRs on this project.",
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
    """Per-user selection of the single active resolution-criteria skill for PostHog Review for a project.

    A resolution skill is any team `review-hog-resolution-*` `LLMSkill` (canonical or custom —
    handled identically at run time): the bar the resolution stage applies to each unresolved
    review thread ("worth implementing" / "safe to implement unattended"). The skill itself is
    team-level; this surface only controls **which one** applies when the stage runs on the
    requesting user's PRs. Visibility is per-user: the menu shows the canonicals (the default
    criteria and its fix profiles) plus the customs the requesting user authored — a teammate's custom is neither listed nor selectable
    (`visible_skill_names`). Like validators (and unlike perspectives), a run applies exactly one,
    so this is a single-active selection: `list` shows the visible skills with the user's active
    one flagged (only the default canonical auto-seeds active on first read; a fix profile is active
    only once selected); `partial_update` selects one by skill name, flipping the user's others off
    in the same call. There is always a default (the default canonical), so no minimum floor is needed.
    """

    # llm_skill, not INTERNAL: responses carry skill body/description, so the llm_analytics RBAC
    # gate must apply — INTERNAL short-circuits AccessControlPermission before it checks anything.
    scope_object = "llm_skill"
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = "review-hog"
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
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        choices = list_review_skill_choices(self.team_id, user_id, ReviewSkillKind.RESOLUTION)
        return Response(ReviewResolutionConfigSerializer(choices, many=True).data)

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
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        try:
            skill = get_review_skill(self.team_id, user_id, ReviewSkillKind.RESOLUTION, skill_name)
        except ReviewSkillNameError:
            raise ValidationError(f"'{skill_name}' is not a review resolution skill")
        except ReviewSkillNotFoundError:
            raise NotFound(f"No resolution skill '{skill_name}' on this project")

        select = ReviewResolutionConfigSelectSerializer(data=request.data)
        select.is_valid(raise_exception=True)
        if not select.validated_data["active"]:
            raise ValidationError(
                "Resolution criteria are single-active — select a different skill instead of deactivating"
            )

        choice = select_review_skill(self.team_id, user_id, ReviewSkillKind.RESOLUTION, skill)
        return Response(ReviewResolutionConfigSerializer(choice).data)
