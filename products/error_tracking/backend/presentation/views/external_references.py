import logging
from uuid import UUID

from drf_spectacular.utils import extend_schema, extend_schema_field, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.facade.api import (
    ExternalReferenceValidationError,
    create_external_reference,
    get_external_reference,
    is_supported_external_issue_provider,
    list_external_references,
    search_external_issues,
)

logger = logging.getLogger(__name__)


@extend_schema_serializer(component_name="ErrorTrackingExternalReferenceIntegrationResult")
class ErrorTrackingExternalReferenceIntegrationSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text="ID of the integration backing this external reference.")
    kind = serializers.CharField(
        read_only=True, help_text="Integration provider, e.g. 'github', 'gitlab', 'linear', or 'jira'."
    )
    display_name = serializers.CharField(read_only=True, help_text="Human-readable name of the connected integration.")


@extend_schema_field({"type": "object", "additionalProperties": {"type": "string"}})
class ExternalReferenceConfigField(serializers.JSONField):
    pass


@extend_schema_field({"type": "object", "additionalProperties": True})
class ExternalReferenceContextField(serializers.JSONField):
    pass


@extend_schema_serializer(component_name="ErrorTrackingExternalReferenceResult")
class ErrorTrackingExternalReferenceSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique ID of the external reference.")
    integration = ErrorTrackingExternalReferenceIntegrationSerializer(
        read_only=True, help_text="The connected integration this reference was created through."
    )
    integration_id = serializers.IntegerField(
        write_only=True,
        help_text="ID of the connected integration to link the external issue with. List the project's integrations to find the right ID and its kind (one of 'github', 'gitlab', 'linear', 'jira').",
    )
    config = ExternalReferenceConfigField(
        write_only=True,
        required=False,
        help_text=(
            "Provider-specific fields describing a NEW external issue to create. Supply this OR external_context, "
            "not both. Required keys depend on the integration kind: github -> {repository, title, body}; "
            "gitlab -> {title, body}; linear -> {team_id, title, description}; "
            "jira -> {project_key, title, description}. Examples: "
            'github {"repository":"posthog","title":"Checkout TypeError","body":"Stack trace"}; '
            'linear {"team_id":"team-id","title":"Checkout TypeError","description":"Stack trace"}; '
            'jira {"project_key":"ENG","title":"Checkout TypeError","description":"Stack trace"}.'
        ),
    )
    external_context = ExternalReferenceContextField(
        write_only=True,
        required=False,
        help_text=(
            "Identifier of an EXISTING external issue to link (from the search-issues endpoint). Supply this OR "
            "config, not both. Required keys depend on the integration kind: github -> {repository, number}; "
            "gitlab -> {issue_id}; linear -> {id}; jira -> {key}."
        ),
    )
    issue = serializers.UUIDField(write_only=True, help_text="ID of the error tracking issue to link the reference to.")
    external_url = serializers.SerializerMethodField(
        help_text="URL of the linked external issue in the provider's system."
    )

    def validate(self, attrs: dict) -> dict:
        has_config = attrs.get("config") is not None
        has_context = attrs.get("external_context") is not None
        if has_config == has_context:
            raise ValidationError(
                "Provide either config (to create a new issue) or external_context (to link an existing one)."
            )
        return attrs

    @extend_schema_field(serializers.CharField())
    def get_external_url(self, reference: contracts.ErrorTrackingExternalReference) -> str:
        if reference.external_url:
            return reference.external_url

        if is_supported_external_issue_provider(reference.integration.kind):
            raise ValidationError("Missing required external context fields")

        raise ValidationError("Provider not supported")


class ErrorTrackingExternalIssueSearchQuerySerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        help_text="ID of the connected integration to search issues in.",
    )
    search = serializers.CharField(
        help_text="Text to match against existing issue titles / keys in the provider.",
    )
    repository = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Repository to search within. Required for GitHub, ignored by other providers.",
    )


@extend_schema_serializer(component_name="ErrorTrackingExternalIssueResult")
class ErrorTrackingExternalIssueResultSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Provider-native identifier of the issue (e.g. issue key or number).")
    title = serializers.CharField(help_text="Human-readable issue title, for display in the picker.")
    url = serializers.CharField(help_text="Link to the issue in the provider's system.")
    external_context = ExternalReferenceContextField(
        help_text="Payload to send back as external_context when creating a reference to this issue.",
    )


@extend_schema_serializer(component_name="ErrorTrackingExternalIssueSearchResult")
class ErrorTrackingExternalIssueSearchResponseSerializer(serializers.Serializer):
    issues = ErrorTrackingExternalIssueResultSerializer(many=True, help_text="Matching existing issues.")


class ErrorTrackingExternalReferenceViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingExternalReferenceSerializer

    def list(self, request, *args, **kwargs):
        references = list_external_references(team_id=self.team.id)

        page = self.paginate_queryset(references)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(references, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        try:
            reference_id = UUID(str(kwargs["pk"]))
        except ValueError as error:
            raise ValidationError("Invalid external reference id") from error

        reference = get_external_reference(reference_id=reference_id, team_id=self.team.id)
        if reference is None:
            raise NotFound("External reference not found")

        serializer = self.get_serializer(reference)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        issue_id = serializer.validated_data["issue"]
        if not isinstance(issue_id, UUID):
            issue_id = UUID(str(issue_id))

        try:
            reference = create_external_reference(
                team_id=self.team.id,
                issue_id=issue_id,
                integration_id=serializer.validated_data["integration_id"],
                config=serializer.validated_data.get("config"),
                external_context=serializer.validated_data.get("external_context"),
            )
        except ExternalReferenceValidationError as error:
            logger.warning("Failed to create external reference", exc_info=error)
            raise ValidationError(str(error)) from error

        response_serializer = self.get_serializer(reference)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[ErrorTrackingExternalIssueSearchQuerySerializer],
        responses={200: ErrorTrackingExternalIssueSearchResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="search_issues", pagination_class=None)
    def search_issues(self, request: Request, *args, **kwargs) -> Response:
        """Search a connected provider for existing issues to link an error to."""
        query_serializer = ErrorTrackingExternalIssueSearchQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        try:
            issues = search_external_issues(
                team_id=self.team.id,
                integration_id=query_serializer.validated_data["integration_id"],
                search=query_serializer.validated_data["search"],
                repository=query_serializer.validated_data.get("repository") or None,
            )
        except ExternalReferenceValidationError as error:
            raise ValidationError(str(error)) from error

        response_serializer = ErrorTrackingExternalIssueSearchResponseSerializer({"issues": issues})
        return Response(response_serializer.data)
