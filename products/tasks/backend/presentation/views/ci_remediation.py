import hmac
import logging
from collections.abc import Mapping

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.tasks.backend.facade import api as tasks_facade

logger = logging.getLogger(__name__)


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data: object) -> dict[str, object]:
        if isinstance(data, Mapping):
            unknown_fields = set(data) - set(self.fields)
            if unknown_fields:
                raise serializers.ValidationError(dict.fromkeys(sorted(unknown_fields), "Unknown field."))
        return super().to_internal_value(data)


class CiRemediationFailingWorkflowSerializer(StrictSerializer):
    name = serializers.CharField(max_length=255, help_text="GitHub Actions workflow display name.")
    run_url = serializers.URLField(max_length=500, help_text="URL of the latest failing GitHub Actions run.")


class CiRemediationTriggerRequestSerializer(StrictSerializer):
    incident_id = serializers.RegexField(
        regex=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        help_text="Stable identifier assigned when the Slack incident opens.",
    )
    repository = serializers.CharField(
        max_length=255,
        help_text="GitHub repository in owner/name form. Only PostHog/posthog is accepted.",
    )
    latest_master_sha = serializers.RegexField(
        regex=r"^[0-9a-fA-F]{40}$",
        help_text="Latest master commit SHA observed by the CI health detector.",
    )
    incident_started_at = serializers.DateTimeField(help_text="Timestamp when sustained master breakage began.")
    failing_workflows = serializers.ListField(
        child=CiRemediationFailingWorkflowSerializer(),
        allow_empty=True,
        max_length=50,
        help_text="Workflows currently sustaining the incident, including their latest failing run URLs.",
    )
    slack_channel_id = serializers.RegexField(
        regex=r"^[A-Z0-9]{2,64}$",
        help_text="Slack channel containing the incident anchor.",
    )
    slack_thread_ts = serializers.RegexField(
        regex=r"^\d{1,20}\.\d{1,20}$",
        help_text="Slack timestamp of the incident anchor and thread root.",
    )


class CiRemediationTriggerResponseSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="PostHog Code task identifier for the incident investigation.")
    run_id = serializers.UUIDField(help_text="PostHog Code cloud run identifier for the incident investigation.")
    task_url = serializers.URLField(help_text="PostHog URL for following the investigation run.")


class CiRemediationTriggerErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Reason the remediation trigger was rejected.")


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return token.strip()


class CiRemediationTriggerViewSet(viewsets.ViewSet):
    authentication_classes = ()
    permission_classes = ()

    def _authenticate(self, request: Request) -> Response | None:
        expected = settings.CI_REMEDIATION_TRIGGER_TOKEN
        if not expected:
            if settings.DEBUG or settings.TEST:
                return None
            return Response(
                {"error": "CI remediation trigger token is not configured"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not hmac.compare_digest(_bearer_token(request), expected):
            return Response({"error": "Invalid trigger token"}, status=status.HTTP_403_FORBIDDEN)
        return None

    @extend_schema(
        request=CiRemediationTriggerRequestSerializer,
        responses={
            202: OpenApiResponse(
                response=CiRemediationTriggerResponseSerializer,
                description="PostHog Code remediation run accepted",
            ),
            400: OpenApiResponse(response=CiRemediationTriggerErrorSerializer, description="Invalid request body"),
            403: OpenApiResponse(
                response=CiRemediationTriggerErrorSerializer,
                description="Missing or invalid token, or disallowed repository",
            ),
            503: OpenApiResponse(
                response=CiRemediationTriggerErrorSerializer,
                description="Server-side remediation configuration is incomplete",
            ),
        },
        summary="Trigger master CI remediation",
        description=(
            "Start or recover the single PostHog Code cloud run assigned to a sustained master CI incident. "
            "The repository, task automation, team, run user, and integrations are resolved server-side. "
            "The incident identifier makes retries idempotent. The response is non-blocking."
        ),
    )
    @action(detail=False, methods=["POST"], url_path="trigger")
    def trigger(self, request: Request) -> Response:
        auth_error = self._authenticate(request)
        if auth_error is not None:
            return auth_error

        serializer = CiRemediationTriggerRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        repository: str = data["repository"]
        if not tasks_facade.is_ci_remediation_repository_allowed(repository):
            return Response({"error": "Repository is not allowed"}, status=status.HTTP_403_FORBIDDEN)

        remediation_run = tasks_facade.trigger_ci_remediation(
            incident_id=data["incident_id"],
            repository=repository,
            latest_master_sha=data["latest_master_sha"].lower(),
            incident_started_at=data["incident_started_at"],
            failing_workflows=tuple((workflow["name"], workflow["run_url"]) for workflow in data["failing_workflows"]),
            slack_channel_id=data["slack_channel_id"],
            slack_thread_ts=data["slack_thread_ts"],
        )
        if remediation_run is None:
            logger.warning("ci_remediation_trigger_configuration_error")
            return Response(
                {"error": "CI remediation is not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response = CiRemediationTriggerResponseSerializer(remediation_run).data
        logger.info(
            "ci_remediation_trigger_accepted",
            extra={"task_id": remediation_run.task_id, "run_id": remediation_run.run_id},
        )
        return Response(response, status=status.HTTP_202_ACCEPTED)
