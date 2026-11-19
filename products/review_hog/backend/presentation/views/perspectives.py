import logging
from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission

from products.review_hog.backend.facade.api import (
    get_review_skill,
    list_review_skill_choices,
    set_review_perspective_enabled,
)
from products.review_hog.backend.facade.contracts import (
    LastEnabledPerspectiveError,
    ReviewSkillNameError,
    ReviewSkillNotFoundError,
)
from products.review_hog.backend.facade.enums import ReviewSkillKind

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
    """Per-user enablement of PostHog Review's review perspectives for a project.

    A perspective is any team `review-hog-perspective-*` `LLMSkill` (canonical or custom — handled
    identically at run time). The skill itself is team-level; this surface only controls **which**
    perspectives run on the requesting user's PR reviews. Visibility is per-user: the menu shows
    the canonicals plus the customs the requesting user authored — a teammate's custom is neither
    listed nor enableable (`visible_skill_names`). `list` joins that menu with the user's enable
    state (the 3 canonicals auto-seed enabled on first read); `partial_update` toggles one by skill
    name (upserting the config row, so a freshly authored custom perspective is enabled by the same
    call). At least one perspective must stay enabled.
    """

    # llm_skill, not INTERNAL: responses carry skill body/description, so the llm_skill RBAC
    # gate must apply — INTERNAL short-circuits AccessControlPermission before it checks anything.
    scope_object = "llm_skill"
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = "review-hog"
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
            "List the `review-hog-perspective-*` skills visible to the requesting user — the "
            "canonical perspectives plus the customs they authored — joined with their enable "
            "state. The 3 canonical perspectives are auto-seeded enabled on the first read; a "
            "custom perspective the user has not switched on shows as disabled."
        ),
    )
    def list(self, request: Request, **kwargs) -> Response:
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        choices = list_review_skill_choices(self.team_id, user_id, ReviewSkillKind.PERSPECTIVE)
        return Response(ReviewPerspectiveConfigSerializer(choices, many=True).data)

    @extend_schema(
        request=ReviewPerspectiveConfigUpdateSerializer,
        responses={
            200: OpenApiResponse(
                response=ReviewPerspectiveConfigSerializer, description="The perspective's updated enable state."
            ),
            400: OpenApiResponse(description="Not a perspective skill, or disabling the user's last enabled one."),
            404: OpenApiResponse(description="No such perspective skill visible to the user on this project."),
        },
        summary="Enable or disable a review perspective",
        description=(
            "Toggle whether a `review-hog-perspective-*` skill runs on the requesting user's PR "
            "reviews. Only skills visible to the user — the canonicals plus the customs they "
            "authored — can be toggled; anything else 404s. Upserts the per-user config row, so "
            "enabling a freshly authored custom perspective works in one call. Rejected if it "
            "would leave the user with no enabled perspective."
        ),
    )
    def partial_update(self, request: Request, skill_name: str, **kwargs) -> Response:
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        try:
            perspective = get_review_skill(self.team_id, user_id, ReviewSkillKind.PERSPECTIVE, skill_name)
        except ReviewSkillNameError:
            raise ValidationError(f"'{skill_name}' is not a review perspective skill")
        except ReviewSkillNotFoundError:
            raise NotFound(f"No perspective skill '{skill_name}' on this project")

        update = ReviewPerspectiveConfigUpdateSerializer(data=request.data)
        update.is_valid(raise_exception=True)
        enabled: bool = update.validated_data["enabled"]

        try:
            choice = set_review_perspective_enabled(self.team_id, user_id, perspective, enabled)
        except LastEnabledPerspectiveError:
            raise ValidationError("Cannot disable your last enabled perspective — at least one must stay on")
        return Response(ReviewPerspectiveConfigSerializer(choice).data)
