"""Imports a CSV file of push device tokens into a push channel in the background, and reads back its progress."""

from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import TeamMemberAdminManagementPermission
from posthog.rate_limit import PushTokenImportThrottle

from products.workflows.backend.facade.enums import PushTokenImportRowFailureReason, PushTokenImportStatus
from products.workflows.backend.facade.push_token_import import (
    MAX_FILE_BYTES,
    PushTokenImportInvalid,
    PushTokenImportNotFound,
    PushTokenImportRecord,
    cancel_push_token_import,
    get_push_token_import,
    import_unknown_persons,
    latest_push_token_import,
    start_push_token_import,
)


@extend_schema_field(OpenApiTypes.BINARY)
class _CsvFileField(serializers.FileField):
    pass


class PushTokenImportCreateSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="The APNs or Firebase push channel to add the devices to.")
    # Session replay redacts a request body with the word "token" in it, so this name keeps uploads out of recordings.
    device_token_file = _CsvFileField(
        help_text=f"A UTF-8 CSV file of up to {MAX_FILE_BYTES // (1024 * 1024)} MB. The first line names the columns: "
        "`distinct_id` (the ID your app passes to identify) and `device_token` (the APNs device token or FCM "
        "registration token). Other columns are ignored."
    )
    create_missing_persons = serializers.BooleanField(
        default=False,
        help_text="Create a person for a distinct ID that has none. Off by default, so devices of unknown people "
        "are listed as failed and can be imported later with new persons.",
    )


class PushTokenImportLatestQuerySerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="The push channel whose newest import to return.")


class PushTokenImportRowFailureSerializer(serializers.Serializer):
    line = serializers.IntegerField(help_text="Line of the file, counting the column names as line 1.")
    distinct_id = serializers.CharField(help_text="The distinct ID on the line.")
    device_token_suffix = serializers.CharField(help_text="The last characters of the line's device token.")
    reason = serializers.ChoiceField(
        choices=PushTokenImportRowFailureReason.choices, help_text="Why the device on this line was not imported."
    )
    detail = serializers.CharField(help_text="A sentence a person can act on.")


class PushTokenImportSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The import's ID.")
    integration_id = serializers.IntegerField(help_text="The push channel the devices are added to.")
    status = serializers.ChoiceField(
        choices=PushTokenImportStatus.choices,
        help_text="`running` while devices are sent. `completed`, `cancelled` and `failed` are final.",
    )
    create_missing_persons = serializers.BooleanField(help_text="Whether the import creates missing persons.")
    total_devices = serializers.IntegerField(help_text="Devices in the file that the import sends.")
    processed_devices = serializers.IntegerField(help_text="Devices sent so far.")
    imported_devices = serializers.IntegerField(help_text="Devices stored on their person.")
    failed_devices = serializers.IntegerField(help_text="Lines that were not imported, for any reason.")
    unknown_person_devices = serializers.IntegerField(help_text="Devices whose distinct ID had no person.")
    duplicate_lines = serializers.IntegerField(help_text="Repeated lines that were left out.")
    failures = PushTokenImportRowFailureSerializer(
        many=True, help_text="The first 1,000 lines that were not imported, with the reason for each."
    )
    can_import_unknown_persons = serializers.BooleanField(
        help_text="True when the devices of unknown people can still be imported with new persons."
    )
    error = serializers.CharField(help_text="Why a failed import stopped. Empty otherwise.")
    created_at = serializers.DateTimeField(help_text="When the file was uploaded.")
    finished_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the import ended. Empty while it runs, and while a stopped import finishes its last batch.",
    )


class PushTokenImportLatestSerializer(serializers.Serializer):
    latest = PushTokenImportSerializer(allow_null=True, help_text="The newest import into the channel, if any.")


class PushTokenImportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "integration"
    scope_object_read_actions = ["retrieve", "latest"]
    scope_object_write_actions = ["create", "cancel", "import_unknown_persons"]
    permission_classes = [TeamMemberAdminManagementPermission]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = PushTokenImportSerializer

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action in self.scope_object_write_actions:
            return ["integration:write", "person:write"]
        return ["integration:read", "person:read"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        # Session users skip API scopes, and access control checks only the integration scope_object.
        writes = self.action in self.scope_object_write_actions
        if not self.user_access_control.check_access_level_for_resource("person", "editor" if writes else "viewer"):
            raise exceptions.PermissionDenied("You need access to persons to import push devices.")

    def get_throttles(self) -> list[Any]:
        if self.action in ("create", "import_unknown_persons"):
            return [PushTokenImportThrottle(), *super().get_throttles()]
        return super().get_throttles()

    @extend_schema(
        request=PushTokenImportCreateSerializer,
        responses={
            201: PushTokenImportSerializer,
            400: OpenApiResponse(description="The file can't be used, or an import into the channel is running."),
        },
        summary="Import a CSV file of push device tokens",
        description="Reads the file and imports its devices into the push channel in the background. "
        "Poll the import to follow its progress.",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = PushTokenImportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["device_token_file"]
        if upload.size > MAX_FILE_BYTES:
            raise exceptions.ValidationError(
                f"This file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB. "
                "Split it into smaller files and import them one at a time."
            )
        try:
            record = start_push_token_import(
                team=self.team,
                user=cast(User, request.user),
                integration_id=serializer.validated_data["integration_id"],
                content=upload.read(),
                create_missing_persons=serializer.validated_data["create_missing_persons"],
            )
        except PushTokenImportInvalid as error:
            raise exceptions.ValidationError(str(error))
        return Response(_serialize(record), status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: PushTokenImportSerializer}, summary="Read a push token import")
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return Response(_serialize(self._run(lambda: get_push_token_import(self.team_id, _uuid(pk)))))

    @validated_request(
        query_serializer=PushTokenImportLatestQuerySerializer,
        responses={200: OpenApiResponse(response=PushTokenImportLatestSerializer)},
        summary="Read the newest push token import of a channel",
    )
    @action(methods=["GET"], detail=False)
    def latest(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        record = latest_push_token_import(self.team_id, request.validated_query_data["integration_id"])
        return Response(PushTokenImportLatestSerializer({"latest": record}).data)

    @extend_schema(request=None, responses={200: PushTokenImportSerializer}, summary="Stop a running push token import")
    @action(methods=["POST"], detail=True)
    def cancel(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return Response(_serialize(self._run(lambda: cancel_push_token_import(self.team_id, _uuid(pk)))))

    @extend_schema(
        request=None,
        responses={
            201: PushTokenImportSerializer,
            400: OpenApiResponse(description="The devices can't be imported again."),
        },
        summary="Import the devices of unknown people with new persons",
        description="Starts a new import of the devices whose distinct ID had no person, creating those persons.",
    )
    @action(methods=["POST"], detail=True)
    def import_unknown_persons(self, request: Request, pk: str, **kwargs: Any) -> Response:
        record = self._run(
            lambda: import_unknown_persons(team=self.team, user=cast(User, request.user), import_id=_uuid(pk))
        )
        return Response(_serialize(record), status=status.HTTP_201_CREATED)

    def _run(self, call: Callable[[], PushTokenImportRecord]) -> PushTokenImportRecord:
        try:
            return call()
        except PushTokenImportNotFound:
            raise exceptions.NotFound("This import doesn't exist.")
        except PushTokenImportInvalid as error:
            raise exceptions.ValidationError(str(error))


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise exceptions.NotFound("This import doesn't exist.")


def _serialize(record: PushTokenImportRecord) -> dict[str, Any]:
    return PushTokenImportSerializer(record).data
