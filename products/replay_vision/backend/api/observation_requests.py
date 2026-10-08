"""API for programmatic scan requests: start scans for named sessions and read them back as one handle."""

from typing import Any, cast

from django.db import models
from django.db.models import Q, QuerySet

import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from pydantic import ValidationError as PydanticValidationError
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.models.user import User
from posthog.permissions import is_authenticated_via_project_secret_api_key, is_scout_sandbox_request
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.replay_vision.backend.api.observations import ScannerResultSerializer
from products.replay_vision.backend.api.scanners import BulkObserveResultSerializer, InlineScanConfigSerializer
from products.replay_vision.backend.models.replay_observation import ObservationStatus
from products.replay_vision.backend.models.replay_observation_request import (
    ObservationRequestSource,
    ReplayObservationRequest,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.observation_requests import (
    InlineScanSpec,
    RequestSession,
    RequestSessionState,
    create_observation_request,
    request_progress,
)
from products.replay_vision.backend.scanner_access import can_read_targeted_experiment, readable_observation_scanner_ids
from products.replay_vision.backend.scanning import MAX_SESSIONS_PER_SCAN
from products.replay_vision.backend.scout_writes import refuse_scout_scanner_scan
from products.replay_vision.backend.session_limits import MAX_SESSION_ID_LENGTH
from products.replay_vision.backend.temporal.types import ScannerResult

logger = structlog.get_logger(__name__)

OBSERVATION_REQUESTS_FLAG = "replay-vision-observation-requests"


class ObservationRequestStatus(models.TextChoices):
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"


class CreateObservationRequestSerializer(serializers.Serializer):
    """Body of POST /vision/requests/ - the sessions plus a saved scanner or an inline question."""

    session_ids = serializers.ListField(
        child=serializers.CharField(max_length=MAX_SESSION_ID_LENGTH),
        allow_empty=False,
        max_length=MAX_SESSIONS_PER_SCAN,
        help_text=(
            f"Session recording IDs to scan, at most {MAX_SESSIONS_PER_SCAN} per request. Scans start until the "
            "in-flight limit or monthly credit quota is reached; the rest are reported as skipped rather than "
            "failing the whole request. Duplicates are dropped."
        ),
    )
    scanner_id = serializers.UUIDField(
        required=False,
        help_text="A saved scanner to apply to the sessions. Pass this or `inline`, not both.",
    )
    inline = InlineScanConfigSerializer(
        required=False,
        help_text=(
            "A question to ask without saving a scanner first. Asking the same question again reuses the "
            "answers already given for the same sessions. Pass this or `scanner_id`, not both."
        ),
    )
    idempotency_key = serializers.CharField(
        required=False,
        max_length=200,
        help_text=(
            "Any unique string per logical request, such as a UUID. Sending the same key again returns the "
            "first request instead of starting new scans, so a retry after a timeout never charges twice."
        ),
    )
    reference = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        help_text="Your own id for this request, such as a ticket or job id. Returned unchanged.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("scanner_id" in attrs) == ("inline" in attrs):
            raise ValidationError("Pass either `scanner_id` or `inline`.")
        attrs["session_ids"] = list(dict.fromkeys(attrs["session_ids"]))
        return attrs


class ObservationRequestSessionSerializer(BulkObserveResultSerializer):
    """One session of a request: how it started and where it stands now."""

    state = serializers.ChoiceField(
        choices=RequestSessionState.choices,
        help_text=(
            "Where the session stands now. 'pending' and 'running' are still in progress; 'succeeded' has a "
            "result; 'failed' and 'ineligible' finished without one; 'skipped' never started because a limit "
            "was reached (`scan_outcome` names which); 'lost' started but produced nothing before the scan "
            "timed out."
        ),
    )
    observation_id = serializers.SerializerMethodField(
        help_text="The observation for this session, once one exists. Null before that."
    )
    scanner_result = serializers.SerializerMethodField(
        help_text="The scanner's answer for this session. Null until the session succeeds."
    )

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_observation_id(self, session: RequestSession) -> str | None:
        return str(session.observation.id) if session.observation is not None else None

    @extend_schema_field(ScannerResultSerializer(allow_null=True))
    def get_scanner_result(self, session: RequestSession) -> dict | None:
        observation = session.observation
        if observation is None or observation.status != ObservationStatus.SUCCEEDED or not observation.scanner_result:
            return None
        try:
            return ScannerResult.model_validate(observation.scanner_result).model_dump(mode="json")
        except PydanticValidationError:
            logger.exception(
                "replay_vision.observation_request.malformed_scanner_result", observation_id=str(observation.id)
            )
            return None


class ObservationRequestSerializer(serializers.Serializer):
    """A scan request and the current state of each of its sessions."""

    id = serializers.UUIDField(help_text="Request ID. Poll `GET /vision/requests/{id}/` with it.")
    status = serializers.ChoiceField(
        choices=ObservationRequestStatus.choices,
        help_text="'completed' once every session has settled, whether or not it produced a result.",
    )
    scanner_id = serializers.UUIDField(
        allow_null=True,
        help_text=(
            "The scanner the sessions were scanned with. For an inline question this is a hidden scanner, "
            "shared by every request that asks the same question. Null when nothing could start."
        ),
    )
    reference = serializers.CharField(help_text="The `reference` sent with the request.")
    created_at = serializers.DateTimeField(help_text="When the request was made.")
    sessions = ObservationRequestSessionSerializer(many=True, help_text="One entry per session, in request order.")


def _distinct_id(request: Request) -> str:
    # Both a real user and the synthetic user a project secret API key authenticates as carry one.
    return str(getattr(request.user, "distinct_id", ""))


class ObservationRequestBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "replay_vision_observation_request_burst"
    rate = "60/minute"


class ObservationRequestSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "replay_vision_observation_request_sustained"
    rate = "1000/hour"


class ObservationRequestPSAKTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "replay_vision_observation_request_psak_team_burst"
    rate = "60/minute"


class ObservationRequestPSAKTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "replay_vision_observation_request_psak_team_sustained"
    rate = "1000/hour"


class ObservationRequestViewSet(
    TeamAndOrgViewSetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Start scans for named sessions from code, and read their results back through one request id."""

    scope_object = "replay_scanner"
    # Reading a request returns what the scanner saw in each recording, so every action needs both scopes.
    required_scopes = ["replay_scanner:write", "session_recording:read"]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["create", "list", "retrieve"]
    serializer_class = ObservationRequestSerializer
    # `objects` is fail-closed; `safely_get_queryset` re-scopes to the request team.
    queryset = ReplayObservationRequest.objects.unscoped()
    http_method_names = ["get", "post", "head", "options"]

    def get_throttles(self) -> list:
        if self.action == "create":
            return [
                ObservationRequestBurstThrottle(),
                ObservationRequestSustainedThrottle(),
                ObservationRequestPSAKTeamBurstThrottle(),
                ObservationRequestPSAKTeamSustainedThrottle(),
            ]
        return super().get_throttles()

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not self._flag_enabled(request):
            raise NotFound()
        if self.action == "create":
            refuse_scout_scanner_scan(is_scout_sandbox_request(request))
        if not self._is_service_call and not self.user_access_control.check_access_level_for_resource(
            "session_recording", required_level="viewer"
        ):
            raise PermissionDenied("Scan requests return recording contents, so they need session recording access.")

    @property
    def _is_service_call(self) -> bool:
        # A project secret API key is project-wide by design, so it skips object-level access checks.
        return is_authenticated_via_project_secret_api_key(self.request)

    def _flag_enabled(self, request: Request) -> bool:
        return bool(
            posthoganalytics.feature_enabled(
                OBSERVATION_REQUESTS_FLAG,
                _distinct_id(request),
                groups={"organization": str(self.team.organization_id), "project": str(self.team.id)},
                group_properties={
                    "organization": {"id": str(self.team.organization_id)},
                    "project": {"id": str(self.team.id)},
                },
                send_feature_flag_events=False,
            )
        )

    def safely_get_queryset(self, queryset: QuerySet[ReplayObservationRequest]) -> QuerySet[ReplayObservationRequest]:
        queryset = queryset.filter(team_id=self.team_id).select_related("scanner").order_by("-created_at")
        if self._is_service_call:
            return queryset
        readable = readable_observation_scanner_ids(self.user_access_control, self.team_id)
        return queryset.filter(Q(scanner_id__in=readable) | Q(scanner__isnull=True))

    def _render(self, request: ReplayObservationRequest) -> dict[str, Any]:
        progress = request_progress(request)
        completed = request.completed_at is not None or progress.settled
        return ObservationRequestSerializer(
            {
                "id": request.id,
                "status": ObservationRequestStatus.COMPLETED if completed else ObservationRequestStatus.RUNNING,
                "scanner_id": request.scanner_id,
                "reference": request.reference,
                "created_at": request.created_at,
                "sessions": progress.sessions,
            }
        ).data

    @extend_schema(responses={200: ObservationRequestSerializer})
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(self._render(self.get_object()))

    @extend_schema(responses={200: ObservationRequestSerializer(many=True)})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        rows = page if page is not None else list(self.get_queryset())
        data = [self._render(r) for r in rows]
        return self.get_paginated_response(data) if page is not None else Response(data)

    @extend_schema(
        request=CreateObservationRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ObservationRequestSerializer,
                description="A request with this `idempotency_key` already exists. Nothing new was started.",
            ),
            202: ObservationRequestSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Scan sessions with a saved scanner or an inline question. Poll the returned request for results."""
        if not self.team.organization.is_ai_data_processing_approved:
            raise ValidationError("Your organization needs to allow AI analysis before you run a Replay Vision scan.")
        body = CreateObservationRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        scanner: ReplayScanner | None = None
        inline: InlineScanSpec | None = None
        if "scanner_id" in data:
            scanner = ReplayScanner.objects.filter(team_id=self.team_id, id=data["scanner_id"]).first()
            if scanner is None:
                raise ValidationError({"scanner_id": "No scanner with this id exists in this project."})
            self._check_can_scan_with(scanner)
        else:
            if not self._is_service_call and not self.user_access_control.check_access_level_for_resource(
                "replay_scanner", required_level="editor"
            ):
                raise PermissionDenied("Asking an inline question requires edit access to the project's scanners.")
            spec = data["inline"]
            inline = InlineScanSpec(
                scanner_type=ScannerType(spec["scanner_type"]),
                scanner_config=spec["scanner_config"],
                model=spec["model"],
            )

        user = None if self._is_service_call else cast(User, request.user)
        observation_request, created = create_observation_request(
            team=self.team,
            user=user,
            source=ObservationRequestSource.PROJECT_SECRET_API_KEY
            if self._is_service_call
            else ObservationRequestSource.USER,
            session_ids=data["session_ids"],
            scanner=scanner,
            inline=inline,
            idempotency_key=data.get("idempotency_key"),
            reference=data["reference"],
        )
        if created:
            self._capture_created(request, observation_request, kind="scanner" if scanner is not None else "inline")
        return Response(
            self._render(observation_request), status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
        )

    def _check_can_scan_with(self, scanner: ReplayScanner) -> None:
        if self._is_service_call:
            return
        if not self.user_access_control.check_access_level_for_object(scanner, "editor"):
            raise PermissionDenied("Scanning with this scanner requires edit access to it.")
        if not can_read_targeted_experiment(self.user_access_control, self.team_id, scanner):
            raise PermissionDenied("Scanning with this scanner requires access to its experiment.")

    def _capture_created(self, request: Request, observation_request: ReplayObservationRequest, *, kind: str) -> None:
        # report_user_action drops synthetic users, so capture directly to count both auth paths alike.
        outcomes = [o["scan_outcome"] for o in observation_request.start_outcomes]
        posthoganalytics.capture(
            distinct_id=_distinct_id(request),
            event="replay_vision_observation_request_created",
            properties={
                "auth_method": observation_request.source,
                "kind": kind,
                "requested": len(observation_request.session_ids),
                "started": outcomes.count("started"),
                "has_idempotency_key": observation_request.idempotency_key is not None,
            },
            groups={"organization": str(self.team.organization_id), "project": str(self.team.uuid)},
        )
