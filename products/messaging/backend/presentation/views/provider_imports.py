from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action

from products.messaging.backend.facade.provider_imports import (
    IMPORT_PROVIDER_CHOICES,
    IMPORT_STEP_STATUS_CHOICES,
    PROVIDER_IMPORT_STATUS_CHOICES,
    ProviderImportConflict,
    ProviderImportRejected,
    get_provider_import_run,
    list_import_providers,
    list_provider_import_runs,
    start_provider_import,
)


class ImportStepOptionSerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text="Step key to send in `steps` when starting an import, for example `suppressions`."
    )
    label = serializers.CharField(help_text="Display name of the step.")  # type: ignore[assignment]  # field named `label` shadows DRF Field.label
    description = serializers.CharField(help_text="What the step imports and where it lands in PostHog.")


class ImportProviderOptionSerializer(serializers.Serializer):
    key = serializers.ChoiceField(
        choices=IMPORT_PROVIDER_CHOICES, help_text="Provider key to send when starting an import."
    )
    label = serializers.CharField(help_text="Display name of the provider.")  # type: ignore[assignment]  # field named `label` shadows DRF Field.label
    steps = ImportStepOptionSerializer(many=True, help_text="What the provider can import, in the order the steps run.")


class ImportStepProgressSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Step key, for example `suppressions`.")
    label = serializers.CharField(help_text="Display name of the step.")  # type: ignore[assignment]  # field named `label` shadows DRF Field.label
    status = serializers.ChoiceField(
        choices=IMPORT_STEP_STATUS_CHOICES,
        help_text="`pending` until the step starts, `running` while it imports or waits to retry, then `completed` or `failed`.",
    )
    processed = serializers.IntegerField(help_text="How many records the step read from the provider so far.")
    imported = serializers.IntegerField(
        help_text="How many records the step added or updated in PostHog so far. Records that already existed and need no change may not count."
    )
    warnings = serializers.ListField(
        child=serializers.CharField(), help_text="Problems with single records that did not fail the step."
    )
    last_error = serializers.CharField(
        allow_null=True,
        help_text="The error from the step's most recent failed attempt. A running step retries after an error; a failed step stopped.",
    )


class ProviderImportRunSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Import run ID.")
    provider = serializers.ChoiceField(choices=IMPORT_PROVIDER_CHOICES, help_text="The provider the run imports from.")
    status = serializers.ChoiceField(
        choices=PROVIDER_IMPORT_STATUS_CHOICES,
        help_text="`queued` until the first step starts, `running`, then `completed` when every step completed or `failed` when any step failed.",
    )
    steps = ImportStepProgressSerializer(many=True, help_text="Progress of each selected step, in run order.")
    created_at = serializers.DateTimeField(help_text="When the run was requested.")
    started_at = serializers.DateTimeField(allow_null=True, help_text="When the first step started.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="When the last step ended.")


class StartProviderImportSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=IMPORT_PROVIDER_CHOICES, help_text="The provider to import from.")
    steps = serializers.ListField(
        child=serializers.CharField(max_length=64),
        min_length=1,
        help_text="Keys of the steps to run, from the `providers` endpoint. They run in the provider's order, whatever order you send.",
    )
    api_key = serializers.CharField(
        required=False,
        write_only=True,
        help_text="The provider's API key. For c.io, an App API key. Leave it out to reuse the stored key.",
    )


class ProviderImportErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Why the import did not start.")


class ProviderImportViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    Background imports from other messaging tools, such as c.io suppressions and global unsubscribes.

    A run executes outside the request, so a long provider list does not time out. Poll a run to show its progress.
    """

    scope_object = "hog_flow"
    serializer_class = _FallbackSerializer

    @extend_schema(
        responses={200: ProviderImportRunSerializer(many=True)}, summary="List the most recent provider imports"
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        return Response(ProviderImportRunSerializer(list_provider_import_runs(self.team_id), many=True).data)

    @extend_schema(responses={200: ProviderImportRunSerializer}, summary="Get a provider import and its progress")
    def retrieve(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            run = get_provider_import_run(self.team_id, UUID(str(pk)))
        except ValueError:
            run = None
        if run is None:
            raise NotFound("Import not found.")
        return Response(ProviderImportRunSerializer(run).data)

    @validated_request(
        request_serializer=StartProviderImportSerializer,
        responses={
            201: OpenApiResponse(response=ProviderImportRunSerializer),
            400: OpenApiResponse(response=ProviderImportErrorSerializer),
            409: OpenApiResponse(response=ProviderImportErrorSerializer),
        },
        summary="Start a background import from another messaging tool",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        # A team-wide write with no per-workflow object, the same as editing the suppression list.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "editor"):
            raise PermissionDenied("You need workflow editor access to import messaging data.")

        data = request.validated_data
        try:
            run = start_provider_import(
                self.team_id, data["provider"], data["steps"], data.get("api_key"), request.user.id
            )
        except ProviderImportRejected as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ProviderImportConflict as e:
            return Response({"error": str(e)}, status=status.HTTP_409_CONFLICT)

        report_user_action(
            request.user,
            "messaging provider import started",
            {"provider": run.provider, "steps": [step.key for step in run.steps]},
            team=self.team,
            request=request,
        )
        return Response(ProviderImportRunSerializer(run).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={200: ImportProviderOptionSerializer(many=True)},
        summary="List the providers and what each can import",
    )
    @action(detail=False, methods=["get"], required_scopes=["hog_flow:read"])
    def providers(self, request: Request, **kwargs: Any) -> Response:
        return Response(ImportProviderOptionSerializer(list_import_providers(), many=True).data)
