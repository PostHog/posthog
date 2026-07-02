import logging

from django.db import transaction
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_VALIDATION_PREFIX,
    register_missing_validation_config,
)
from products.skills.backend.models.skills import LLMSkill

logger = logging.getLogger(__name__)


class ReviewValidatorConfigSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        help_text="Name of the `review-hog-validation-*` skill this row represents (the validator's identity)."
    )
    active = serializers.BooleanField(
        help_text="Whether this validator is the one that validates the requesting user's PR reviews on this project."
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
    """Per-user selection of ReviewHog's single active review validator for a project.

    A validator is any team `review-hog-validation-*` `LLMSkill` (canonical or custom — handled
    identically). The skill itself is team-level; this surface only controls **which one** validates
    the requesting user's PR reviews. Unlike perspectives (multi-enable), a review runs exactly one
    validator, so this is a single-active selection: `list` shows every validator with the user's
    active one flagged (the canonical auto-seeds active on first read); `partial_update` selects one
    by skill name, flipping the user's other validators off in the same call. There is always a
    default (the canonical), so no minimum floor is needed.
    """

    scope_object = "INTERNAL"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewSkillConfig.objects.unscoped()
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
            "List every `review-hog-validation-*` skill on this project, flagging the one active for "
            "the requesting user. The canonical validator is auto-seeded active on the first read; a "
            "custom validator the user has not selected shows as inactive."
        ),
    )
    def list(self, request: Request, **kwargs) -> Response:
        register_missing_validation_config(self.team_id, request.user.id)
        active_by_name = dict(
            ReviewSkillConfig.objects.for_team(self.team_id)
            .filter(user_id=request.user.id, skill_name__startswith=REVIEW_HOG_VALIDATION_PREFIX)
            .values_list("skill_name", "enabled")
        )
        skills = LLMSkill.objects.filter(
            team_id=self.team_id, name__startswith=REVIEW_HOG_VALIDATION_PREFIX, is_latest=True, deleted=False
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
        return Response(ReviewValidatorConfigSerializer(items, many=True).data)

    @extend_schema(
        request=ReviewValidatorConfigSelectSerializer,
        responses={
            200: OpenApiResponse(
                response=ReviewValidatorConfigSerializer, description="The validator now active for the user."
            ),
            400: OpenApiResponse(description="Not a validator skill, or `active` was not true."),
            404: OpenApiResponse(description="No such validator skill on this project."),
        },
        summary="Select the active review validator",
        description=(
            "Make a `review-hog-validation-*` skill the single validator that runs on the requesting "
            "user's PR reviews, switching the user's other validators off in the same call. Upserts the "
            "per-user config row, so selecting a freshly authored custom validator works in one call."
        ),
    )
    def partial_update(self, request: Request, skill_name: str, **kwargs) -> Response:
        if not skill_name.startswith(REVIEW_HOG_VALIDATION_PREFIX):
            raise ValidationError(f"'{skill_name}' is not a review validator skill")
        skill = LLMSkill.objects.filter(team_id=self.team_id, name=skill_name, is_latest=True, deleted=False).first()
        if skill is None:
            raise NotFound(f"No validator skill '{skill_name}' on this project")

        select = ReviewValidatorConfigSelectSerializer(data=request.data)
        select.is_valid(raise_exception=True)
        if not select.validated_data["active"]:
            raise ValidationError("Validators are single-active — select a different validator instead of deactivating")

        register_missing_validation_config(self.team_id, request.user.id)
        configs = ReviewSkillConfig.objects.for_team(self.team_id)
        # Single-active: deactivate-others + activate-this must land together, or a crash between them
        # leaves the user with no active validator (the loader's canonical fallback would heal it).
        with transaction.atomic():
            configs.filter(
                user_id=request.user.id, skill_name__startswith=REVIEW_HOG_VALIDATION_PREFIX, enabled=True
            ).exclude(skill_name=skill_name).update(enabled=False, updated_at=timezone.now())
            # `team_id` / `user_id` stay in the create kwargs — the fail-closed filter doesn't propagate.
            config, _created = configs.get_or_create(
                team_id=self.team_id, user_id=request.user.id, skill_name=skill_name, defaults={"enabled": True}
            )
            if not config.enabled:
                config.enabled = True
                config.save(update_fields=["enabled", "updated_at"])
        return Response(
            ReviewValidatorConfigSerializer(
                {"skill_name": skill_name, "active": True, "description": skill.description, "body": skill.body}
            ).data
        )
