"""A member's own standing instructions to stay off automatic reviewer selection in one area.

A member manages only the instructions that name them. The project access checks of the
`task` scope apply, and no scout-edit permission is necessary.
"""

from __future__ import annotations

from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.permissions import APIScopePermission

from products.signals.backend.models import SignalReviewerExclusion
from products.signals.backend.reviewer_exclusions import create_exclusion, revise_exclusion, revoke_exclusion
from products.signals.backend.reviewer_rules import ReviewerWriteError, StaleReviewerProposal
from products.signals.backend.views import remove_suggested_reviewer

logger = structlog.get_logger(__name__)

MAX_INSTRUCTION_LENGTH = 2000


class ReviewerExclusionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Identifier of the instruction.")
    repository = serializers.CharField(
        read_only=True, help_text="Repository in `owner/name` form that the instruction covers. Empty covers every one."
    )
    path_prefix = serializers.CharField(
        read_only=True, help_text="Path inside the repository that the instruction covers. Empty covers the repository."
    )
    instruction = serializers.CharField(read_only=True, help_text="Why the member stays off this area.")
    status = serializers.ChoiceField(
        choices=SignalReviewerExclusion.Status.choices,
        read_only=True,
        help_text="`active` instructions apply to automatic reviewer selection. `revoked` instructions do not.",
    )
    revision = serializers.IntegerField(read_only=True, help_text="Increases by one at each change.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the member saved the instruction.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the instruction last changed.")

    class Meta:
        model = SignalReviewerExclusion
        fields = ["id", "repository", "path_prefix", "instruction", "status", "revision", "created_at", "updated_at"]


class ReviewerExclusionAreaSerializer(serializers.Serializer):
    repository = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="Repository in `owner/name` form. Leave empty to cover every repository.",
    )
    path_prefix = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Path inside the repository, such as `src/billing`. Needs a repository.",
    )


class ReviewerExclusionCreateSerializer(ReviewerExclusionAreaSerializer):
    instruction = serializers.CharField(
        max_length=MAX_INSTRUCTION_LENGTH, help_text="Why you stay off this area, for the people who read it later."
    )
    report_id = serializers.UUIDField(
        required=False,
        help_text=(
            "Optional report to take you off first. The report removal and the instruction save are separate steps."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("path_prefix") and not attrs.get("repository"):
            raise serializers.ValidationError({"path_prefix": "Give a repository for a path."})
        return attrs


class ReviewerExclusionUpdateSerializer(ReviewerExclusionAreaSerializer):
    instruction = serializers.CharField(
        required=False, max_length=MAX_INSTRUCTION_LENGTH, help_text="New text for the instruction."
    )


class ReviewerExclusionCreateResultSerializer(serializers.Serializer):
    instruction_saved = serializers.BooleanField(
        help_text="True only when the instruction is saved. Only then does it keep you off automatic selection."
    )
    report_removed = serializers.BooleanField(
        allow_null=True, help_text="True when the report removal succeeded. Null when no report was given."
    )
    exclusion = ReviewerExclusionSerializer(allow_null=True, help_text="The saved instruction, or null.")
    detail = serializers.CharField(help_text="What happened, and what to do next.")


class ReviewerExclusionErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the request failed.")


def _create_result(
    *, exclusion: SignalReviewerExclusion | None, report_removed: bool | None, detail: str, response_status: int
) -> Response:
    payload = {
        "instruction_saved": exclusion is not None,
        "report_removed": report_removed,
        "exclusion": exclusion,
        "detail": detail,
    }
    return Response(ReviewerExclusionCreateResultSerializer(payload).data, status=response_status)


@extend_schema_view(
    list=extend_schema(
        summary="List your reviewer exclusions",
        description="List the standing instructions that keep you off automatic reviewer selection, active and revoked.",
    ),
    retrieve=extend_schema(summary="Get one of your reviewer exclusions"),
)
class SignalReviewerExclusionViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ReviewerExclusionSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    queryset = SignalReviewerExclusion.objects.unscoped()
    pagination_class = None

    def _should_skip_parents_filter(self) -> bool:
        # `for_team` below reads the canonical team, where the model saves its rows.
        return True

    def safely_get_queryset(self, queryset: Any) -> Any:
        return (
            SignalReviewerExclusion.objects.for_team(self.team_id)
            .filter(subject_user_uuid=cast(User, self.request.user).uuid)
            .order_by("-created_at", "-id")
        )

    @extend_schema(
        summary="Stay off automatic reviewer selection in an area",
        request=ReviewerExclusionCreateSerializer,
        responses={
            201: ReviewerExclusionCreateResultSerializer,
            207: OpenApiResponse(
                response=ReviewerExclusionCreateResultSerializer,
                description="The report removal succeeded but the instruction is not saved. Send the request again.",
            ),
            400: ReviewerExclusionErrorSerializer,
            404: ReviewerExclusionErrorSerializer,
            409: ReviewerExclusionErrorSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = ReviewerExclusionCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        user = cast(User, request.user)

        report_removed: bool | None = None
        if report_id := data.get("report_id"):
            try:
                remove_suggested_reviewer(team=self.team, report_id=str(report_id), user=user, request=request)
            except StaleReviewerProposal as e:
                return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
            except ReviewerWriteError as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            report_removed = True

        try:
            exclusion = create_exclusion(
                team_id=self.team_id,
                actor_id=user.id,
                instruction=data["instruction"],
                subject_user_uuid=user.uuid,
                subject_github_login=user.get_github_login(include_team_fallback=False),
                repository=data.get("repository", ""),
                path_prefix=data.get("path_prefix", ""),
            )
        except Exception as e:
            if report_removed is None:
                raise
            capture_exception(e)
            logger.exception("signals.reviewer_exclusion.save_failed", team_id=self.team_id, report_id=str(report_id))
            return _create_result(
                exclusion=None,
                report_removed=True,
                detail=(
                    "You are off this report, but the instruction is not saved, so automatic selection can still "
                    "pick you. Send the request again."
                ),
                response_status=status.HTTP_207_MULTI_STATUS,
            )

        return _create_result(
            exclusion=exclusion,
            report_removed=report_removed,
            detail="Saved. Automatic reviewer selection no longer picks you in this area.",
            response_status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Change one of your reviewer exclusions",
        request=ReviewerExclusionUpdateSerializer,
        responses={200: ReviewerExclusionSerializer, 400: ReviewerExclusionErrorSerializer},
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        exclusion = cast(SignalReviewerExclusion, self.get_object())
        payload = ReviewerExclusionUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        repository = data.get("repository", exclusion.repository).strip()
        path_prefix = data.get("path_prefix", exclusion.path_prefix).strip()
        if path_prefix and not repository:
            return Response({"detail": "Give a repository for a path."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            revised = revise_exclusion(
                team_id=self.team_id,
                exclusion_id=exclusion.id,
                actor_id=cast(User, request.user).id,
                instruction=data.get("instruction"),
                repository=data.get("repository"),
                path_prefix=data.get("path_prefix"),
            )
        except SignalReviewerExclusion.DoesNotExist:
            return Response({"detail": "A revoked instruction cannot change."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ReviewerExclusionSerializer(revised).data)

    @extend_schema(
        summary="Revoke one of your reviewer exclusions",
        description=(
            "Make you eligible for automatic reviewer selection in this area again. Revoking does not add you to "
            "any report, and it does not change old reports."
        ),
        request=None,
        responses={200: ReviewerExclusionSerializer},
    )
    @action(detail=True, methods=["post"], url_path="revoke", required_scopes=["task:write"])
    def revoke(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        exclusion = cast(SignalReviewerExclusion, self.get_object())
        revoked = revoke_exclusion(
            team_id=self.team_id, exclusion_id=exclusion.id, actor_id=cast(User, request.user).id
        )
        return Response(ReviewerExclusionSerializer(revoked).data)
