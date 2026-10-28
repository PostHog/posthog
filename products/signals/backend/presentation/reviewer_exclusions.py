"""A member's own standing instructions to stay off automatic reviewer selection in one area.

A member manages only the instructions that name them. The `task` scope applies, and the member
needs access to the canonical project, where the instructions live. No scout-edit permission is
necessary.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.activity_logging.model_activity import is_impersonated_session
from posthog.permissions import APIScopePermission, get_authenticator_scoped_team_ids

from products.signals.backend.facade.reviewer_exclusions import (
    DuplicateExclusion,
    PathWithoutRepository,
    ReviewerExclusion,
    ReviewerExclusionNotFound,
    ReviewerExclusionStatus,
    ReviewerWriteError,
    RevokedExclusion,
    create_own_exclusion,
    get_own_exclusion,
    list_own_exclusions,
    remove_report_reviewer,
    revise_own_exclusion,
    revoke_own_exclusion,
    sanitized_repository,
)
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission

logger = structlog.get_logger(__name__)

MAX_INSTRUCTION_LENGTH = 2000


class ReviewerExclusionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Identifier of the instruction.")
    repository = serializers.CharField(
        read_only=True, help_text="Repository in `owner/name` form that the instruction covers. Empty covers every one."
    )
    path_prefix = serializers.CharField(
        read_only=True, help_text="Path inside the repository that the instruction covers. Empty covers the repository."
    )
    instruction = serializers.CharField(read_only=True, help_text="Why the member stays off this area.")
    status = serializers.ChoiceField(
        choices=ReviewerExclusionStatus.choices,
        read_only=True,
        help_text="`active` instructions apply to automatic reviewer selection. `revoked` instructions do not.",
    )
    revision = serializers.IntegerField(read_only=True, help_text="Increases by one at each change.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the member saved the instruction.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the instruction last changed.")


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

    def validate_repository(self, value: str) -> str:
        # Matching compares the stored value to a report's `owner/name` exactly, so a URL never matches.
        if value and sanitized_repository(value) is None:
            raise serializers.ValidationError("Use the `owner/name` form, such as `posthog/posthog`.")
        return value

    def validate_path_prefix(self, value: str) -> str:
        # Matching compares whole path segments, so `.`, `..` or an empty segment never matches.
        if value and any(segment in {"", ".", ".."} for segment in value.split("/")):
            raise serializers.ValidationError(
                "Use a relative path such as `src/billing`, with no leading or trailing slash and no `.` or `..` parts."
            )
        return value


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
    *, exclusion: ReviewerExclusion | None, report_removed: bool | None, detail: str, response_status: int
) -> Response:
    payload = {
        "instruction_saved": exclusion is not None,
        "report_removed": report_removed,
        "exclusion": exclusion,
        "detail": detail,
    }
    return Response(ReviewerExclusionCreateResultSerializer(payload).data, status=response_status)


_EXCLUSION_ID = OpenApiParameter(
    "id",
    OpenApiTypes.UUID,
    OpenApiParameter.PATH,
    description="A UUID string identifying this signal reviewer exclusion.",
)


class SignalReviewerExclusionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = ReviewerExclusionSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "task"
    pagination_class = None

    def _exclusion_id(self) -> UUID:
        try:
            return UUID(str(self.kwargs["pk"]))
        except ValueError:
            raise NotFound()

    @extend_schema(
        summary="List your reviewer exclusions",
        description="List the standing instructions that keep you off automatic reviewer selection, active and revoked.",
        responses={200: ReviewerExclusionSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        exclusions = list_own_exclusions(team_id=self.team_id, user=cast(User, request.user))
        return Response(ReviewerExclusionSerializer(exclusions, many=True).data)

    @extend_schema(
        summary="Get one of your reviewer exclusions",
        parameters=[_EXCLUSION_ID],
        responses={200: ReviewerExclusionSerializer},
    )
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            exclusion = get_own_exclusion(
                team_id=self.team_id, user=cast(User, request.user), exclusion_id=self._exclusion_id()
            )
        except ReviewerExclusionNotFound:
            raise NotFound()
        return Response(ReviewerExclusionSerializer(exclusion).data)

    @extend_schema(
        summary="Stay off automatic reviewer selection in an area",
        request=ReviewerExclusionCreateSerializer,
        responses={
            200: OpenApiResponse(
                response=ReviewerExclusionCreateResultSerializer,
                description="An active instruction already covers this area, so nothing new is saved.",
            ),
            201: ReviewerExclusionCreateResultSerializer,
            207: OpenApiResponse(
                response=ReviewerExclusionCreateResultSerializer,
                description="The report removal succeeded but the instruction is not saved. Send the request again.",
            ),
            400: ReviewerExclusionErrorSerializer,
            404: ReviewerExclusionErrorSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = ReviewerExclusionCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        user = cast(User, request.user)

        report_removed: bool | None = None
        if report_id := data.get("report_id"):
            scoped_team_ids = get_authenticator_scoped_team_ids(request.successful_authenticator)
            try:
                remove_report_reviewer(
                    team=self.team,
                    report_id=str(report_id),
                    user=user,
                    scoped_team_ids=tuple(scoped_team_ids) if scoped_team_ids is not None else None,
                    was_impersonated=is_impersonated_session(request),
                )
            except ReviewerWriteError as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            report_removed = True

        try:
            exclusion, created = create_own_exclusion(
                team_id=self.team_id,
                user=user,
                instruction=data["instruction"],
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
            detail="Saved. Automatic reviewer selection no longer picks you in this area."
            if created
            else "Already saved. Automatic reviewer selection does not pick you in this area.",
            response_status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Change one of your reviewer exclusions",
        parameters=[_EXCLUSION_ID],
        request=ReviewerExclusionUpdateSerializer,
        responses={200: ReviewerExclusionSerializer, 400: ReviewerExclusionErrorSerializer},
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        exclusion_id = self._exclusion_id()
        payload = ReviewerExclusionUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            revised = revise_own_exclusion(
                team_id=self.team_id,
                user=cast(User, request.user),
                exclusion_id=exclusion_id,
                instruction=data.get("instruction"),
                repository=data.get("repository"),
                path_prefix=data.get("path_prefix"),
            )
        except ReviewerExclusionNotFound:
            raise NotFound()
        except PathWithoutRepository as e:
            raise serializers.ValidationError({"path_prefix": str(e)})
        except (DuplicateExclusion, RevokedExclusion) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ReviewerExclusionSerializer(revised).data)

    @extend_schema(
        summary="Revoke one of your reviewer exclusions",
        description=(
            "Make you eligible for automatic reviewer selection in this area again. Revoking does not add you to "
            "any report, and it does not change old reports."
        ),
        parameters=[_EXCLUSION_ID],
        request=None,
        responses={200: ReviewerExclusionSerializer},
    )
    @action(detail=True, methods=["post"], url_path="revoke", required_scopes=["task:write"])
    def revoke(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            revoked = revoke_own_exclusion(
                team_id=self.team_id, user=cast(User, request.user), exclusion_id=self._exclusion_id()
            )
        except ReviewerExclusionNotFound:
            raise NotFound()
        return Response(ReviewerExclusionSerializer(revoked).data)
