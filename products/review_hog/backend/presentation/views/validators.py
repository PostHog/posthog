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


class ReviewValidatorConfigSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        help_text="Name of the `review-hog-validation-*` skill this row represents (the validator's identity)."
    )
    active = serializers.BooleanField(
        source="enabled",
        help_text="Whether this validator is the one that validates the requesting user's PR reviews on this project.",
    )
    description = serializers.CharField(
        allow_blank=True, help_text="The validator skill's description, for display in the config UI."
    )
    body = serializers.CharField(
        allow_blank=True, help_text="The validator skill's SKILL.md body, for the read-only skill viewer."
    )


class ReviewValidatorConfigSelectSerializer(serializers.Serializer):
    active = serializers.BooleanField(
        help_text=(
            "Set true to make this the single validator that runs on the user's PR reviews. Only true is "
            "accepted — validators are single-active, so you switch by selecting a different one, not by "
            "deactivating the current one."
        )
    )


class ReviewValidatorConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Per-user selection of the single active review validator for PostHog Review for a project.

    A validator is any team `review-hog-validation-*` `LLMSkill` (canonical or custom — handled
    identically at run time). The skill itself is team-level; this surface only controls **which
    one** validates the requesting user's PR reviews. Visibility is per-user: the menu shows the
    canonical plus the customs the requesting user authored — a teammate's custom is neither listed
    nor selectable (`visible_skill_names`). Unlike perspectives (multi-enable), a review runs
    exactly one validator, so this is a single-active selection: `list` shows the visible
    validators with the user's active one flagged (the canonical auto-seeds active on first read);
    `partial_update` selects one by skill name, flipping the user's other validators off in the
    same call. There is always a default (the canonical), so no minimum floor is needed.
    """

    # llm_skill, not INTERNAL: responses carry skill body/description, so the llm_skill RBAC
    # gate must apply — INTERNAL short-circuits AccessControlPermission before it checks anything.
    scope_object = "llm_skill"
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = "review-hog"
    serializer_class = ReviewValidatorConfigSerializer
    lookup_field = "skill_name"
    pagination_class = None

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ReviewValidatorConfigSerializer(many=True),
                description="Every review validator on this project, flagging the one active for the user.",
            ),
        },
        summary="List review validators and which one is active",
        description=(
            "List the `review-hog-validation-*` skills visible to the requesting user — the "
            "canonical validator plus the customs they authored — flagging the one active for "
            "them. The canonical validator is auto-seeded active on the first read; a custom "
            "validator the user has not selected shows as inactive."
        ),
    )
    def list(self, request: Request, **kwargs) -> Response:
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        choices = list_review_skill_choices(self.team_id, user_id, ReviewSkillKind.VALIDATION)
        return Response(ReviewValidatorConfigSerializer(choices, many=True).data)

    @extend_schema(
        request=ReviewValidatorConfigSelectSerializer,
        responses={
            200: OpenApiResponse(
                response=ReviewValidatorConfigSerializer, description="The validator now active for the user."
            ),
            400: OpenApiResponse(description="Not a validator skill, or `active` was not true."),
            404: OpenApiResponse(description="No such validator skill visible to the user on this project."),
        },
        summary="Select the active review validator",
        description=(
            "Make a `review-hog-validation-*` skill the single validator that runs on the requesting "
            "user's PR reviews, switching the user's other validators off in the same call. Only "
            "skills visible to the user — the canonical plus the customs they authored — can be "
            "selected; anything else 404s. Upserts the per-user config row, so selecting a freshly "
            "authored custom validator works in one call."
        ),
    )
    def partial_update(self, request: Request, skill_name: str, **kwargs) -> Response:
        user_id = cast(int, request.user.id)  # authenticated via the viewset mixin
        try:
            skill = get_review_skill(self.team_id, user_id, ReviewSkillKind.VALIDATION, skill_name)
        except ReviewSkillNameError:
            raise ValidationError(f"'{skill_name}' is not a review validator skill")
        except ReviewSkillNotFoundError:
            raise NotFound(f"No validator skill '{skill_name}' on this project")

        select = ReviewValidatorConfigSelectSerializer(data=request.data)
        select.is_valid(raise_exception=True)
        if not select.validated_data["active"]:
            raise ValidationError("Validators are single-active — select a different validator instead of deactivating")

        choice = select_review_skill(self.team_id, user_id, ReviewSkillKind.VALIDATION, skill)
        return Response(ReviewValidatorConfigSerializer(choice).data)
