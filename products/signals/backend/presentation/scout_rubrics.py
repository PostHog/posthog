from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission

from products.signals.backend.facade.rubrics import (
    MAX_CRITERIA,
    RUBRIC_TEAM_ID,
    ScoutRubricCriterion,
    ScoutRubricDocument,
    ScoutRubricGenerationLimitExceeded,
    ScoutRubricGenerationStatus,
    ScoutRubricGenerationUnavailable,
    ScoutRubricNotFound,
    ScoutRubricSource,
    default_criteria,
    generate_scout_rubric,
    get_scout_rubric,
    save_scout_rubric,
)

if TYPE_CHECKING:
    from rest_framework.views import APIView


class ScoutRubricCriterionSerializer(serializers.Serializer):
    id = serializers.RegexField(r"^[a-z][a-z0-9_-]{0,79}$", max_length=80, help_text="Stable criterion identifier.")
    title = serializers.CharField(max_length=120, help_text="Short name for the criterion.")
    description = serializers.CharField(max_length=1000, help_text="What this criterion measures.")
    pass_condition = serializers.CharField(max_length=2000, help_text="The evidence needed to pass this criterion.")
    applicability = serializers.CharField(
        max_length=1000, help_text="When this criterion applies or cannot be assessed."
    )
    enabled = serializers.BooleanField(help_text="Whether future evaluations should use this criterion.")
    source = serializers.ChoiceField(  # type: ignore[assignment]  # The field name shadows DRF Field.source.
        choices=ScoutRubricSource.choices, help_text="Shared default or scout-specific criterion."
    )


class ScoutRubricGenerationSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Identifier for this generation attempt.")
    status = serializers.ChoiceField(
        choices=ScoutRubricGenerationStatus.choices, help_text="Background generation status."
    )
    requested_at = serializers.DateTimeField(help_text="When generation was requested.")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="When generation completed or failed.")
    task_id = serializers.UUIDField(allow_null=True, help_text="Task performing the investigation, once created.")
    task_run_id = serializers.UUIDField(
        allow_null=True, help_text="Task run performing the investigation, once created."
    )
    error = serializers.CharField(allow_null=True, help_text="Failure message and suggested next step.")
    suggestions = ScoutRubricCriterionSerializer(
        many=True, help_text="Draft criteria awaiting review and explicit saving."
    )
    summary = serializers.CharField(allow_blank=True, help_text="Investigation summary and limitations.")


class ScoutRubricDocumentSerializer(serializers.Serializer):
    config_id = serializers.UUIDField(help_text="Scout config that owns this rubric.")
    skill_name = serializers.CharField(help_text="Scout skill name.")
    revision = serializers.IntegerField(
        min_value=0, help_text="Saved rubric revision. Zero means it has not been saved."
    )
    criteria = ScoutRubricCriterionSerializer(
        many=True, help_text="Saved criteria, or enabled defaults before the first save."
    )
    generation = ScoutRubricGenerationSerializer(allow_null=True, help_text="Latest background generation, if any.")


class ScoutRubricSaveSerializer(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0, help_text="Revision read by the editor; stale saves return 409.")
    criteria: serializers.ListSerializer[dict[str, str | bool]] = serializers.ListSerializer(
        child=ScoutRubricCriterionSerializer(), max_length=MAX_CRITERIA, help_text="Complete set of criteria to save."
    )

    def validate_criteria(self, value: list[dict[str, str | bool]]) -> list[dict[str, str | bool]]:
        ids = [item["id"] for item in value]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Each criterion needs a unique identifier.")
        default_ids = {item.id for item in default_criteria()}
        for item in value:
            if (item["id"] in default_ids) != (item["source"] == ScoutRubricSource.DEFAULT):
                raise serializers.ValidationError("Default criteria must keep their original identifiers and source.")
            if item["source"] == ScoutRubricSource.CUSTOM and not str(item["id"]).startswith("custom-"):
                raise serializers.ValidationError("Custom criterion identifiers must start with 'custom-'.")
        return value


class ScoutRubricAccessPermission(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(getattr(request.user, "is_staff", False) and getattr(view, "team_id", None) == RUBRIC_TEAM_ID)


def rubric_response(document: ScoutRubricDocument, *, response_status: int = status.HTTP_200_OK) -> Response:
    payload = {
        "config_id": document.config_id,
        "skill_name": document.skill_name,
        **document.state.model_dump(mode="json"),
    }
    return Response(ScoutRubricDocumentSerializer(payload).data, status=response_status)


@extend_schema(
    parameters=[
        OpenApiParameter(
            "id",
            OpenApiTypes.UUID,
            OpenApiParameter.PATH,
            description="A UUID string identifying this Signal scout config.",
        )
    ]
)
class SignalScoutRubricViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = ScoutRubricDocumentSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutRubricAccessPermission]
    scope_object = "signal_scout"
    lookup_field = "id"
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str]:
        return ["signal_scout:read" if getattr(view, "action", None) == "retrieve" else "signal_scout:write"]

    def get_rubric(self, config_id: str) -> ScoutRubricDocument:
        try:
            document = get_scout_rubric(self.team_id, config_id)
        except ScoutRubricNotFound:
            raise exceptions.NotFound() from None
        self.check_object_permissions(self.request, document)
        return document

    @extend_schema(responses={200: ScoutRubricDocumentSerializer}, operation_id="signals_scout_rubrics_retrieve")
    def retrieve(self, request: Request, id: str, **kwargs: object) -> Response:
        return rubric_response(self.get_rubric(id))

    @extend_schema(
        request=ScoutRubricSaveSerializer,
        responses={200: ScoutRubricDocumentSerializer, 409: OpenApiResponse(description="The saved revision changed.")},
        operation_id="signals_scout_rubrics_update",
    )
    def update(self, request: Request, id: str, **kwargs: object) -> Response:
        document = self.get_rubric(id)
        serializer = ScoutRubricSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = save_scout_rubric(
            self.team_id,
            str(document.config_id),
            revision=serializer.validated_data["revision"],
            criteria=[ScoutRubricCriterion.model_validate(item) for item in serializer.validated_data["criteria"]],
        )
        return rubric_response(document)

    @extend_schema(
        request=None,
        responses={202: ScoutRubricDocumentSerializer},
        operation_id="signals_scout_rubrics_generate",
    )
    @action(detail=True, methods=["post"])
    def generate(self, request: Request, id: str, **kwargs: object) -> Response:
        document = self.get_rubric(id)
        user_id = request.user.pk
        if user_id is None:
            raise exceptions.NotAuthenticated()
        if self.team.organization.is_ai_data_processing_approved is not True:
            raise exceptions.PermissionDenied("Enable AI data processing for this organization to generate rubrics.")
        try:
            document = generate_scout_rubric(self.team_id, str(document.config_id), user_id=user_id)
        except ScoutRubricGenerationLimitExceeded:
            raise exceptions.Throttled(
                detail="You've reached today's rubric generation limit. Try again tomorrow."
            ) from None
        except ScoutRubricGenerationUnavailable:
            raise exceptions.APIException("Generation could not start. Try again.") from None
        return rubric_response(document, response_status=status.HTTP_202_ACCEPTED)
