from typing import Any, cast
from uuid import UUID

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.models import Team

from products.cdp.backend.presentation.hog_functions import gated_template_enabled
from products.tasks.backend.facade.workflow_tasks import get_workflow_task_run_final_message
from products.workflows.backend.facade.service_jwt import WORKFLOW_EXTRACT_PURPOSE
from products.workflows.backend.presentation.views.workflow_classifications import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_DEPTH,
    validate_workflow_context,
)
from products.workflows.backend.services.ai_extraction import (
    MAX_TEXT_VALUE_CHARS,
    ExtractionBudgetExceededError,
    ExtractionField,
    ExtractionFieldType,
    ExtractionModelBusyError,
    ExtractionModelRefusedError,
    ExtractionUnavailableError,
    ExtractionUnusableError,
    extract_fields,
)

logger = structlog.get_logger(__name__)

# Matches the AI task step's output fields, so a field name is always addressable as `variables.<name>`.
MAX_FIELDS = 20
# \Z, not $: Python's $ also matches before a trailing newline, which the worker's pattern rejects.
FIELD_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}\Z"
MAX_INSTRUCTION_LENGTH = 500


class WorkflowExtractJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_EXTRACT_PURPOSE

    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        if not claims.get("hog_flow_id"):
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return super()._authenticate_claims(request, claims)


class WorkflowExtractionFieldSerializer(serializers.Serializer):
    name = serializers.RegexField(
        FIELD_NAME_PATTERN,
        trim_whitespace=False,
        error_messages={
            "invalid": "Use only letters, digits and underscores, start with a letter or underscore, and keep it to 64 characters."
        },
        help_text="The field name: letters, digits and underscores, not starting with a digit. At most 64 characters.",
    )
    type = serializers.ChoiceField(
        choices=ExtractionFieldType.choices,
        default=ExtractionFieldType.STRING,
        help_text="The type of the value. Defaults to text.",
    )
    instruction = serializers.CharField(
        max_length=MAX_INSTRUCTION_LENGTH,
        help_text="What to put in the field, for example 'The URL of the pull request the agent opened'.",
    )


class WorkflowExtractionRequestSerializer(serializers.Serializer):
    context = serializers.JSONField(  # type: ignore[assignment]  # The field name shadows DRF Field.context.
        required=False,
        allow_null=True,
        default=None,
        help_text=f"The output of an earlier step to read, such as a webhook response. The model reads it as data, never as instructions. At most {MAX_CONTEXT_CHARS} characters of JSON and {MAX_CONTEXT_DEPTH} levels of nesting. Required unless task_run_id is set.",
    )
    task_run_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="The run of an AI task step earlier in this workflow. When set, the model reads that run's full final message in place of context.",
    )
    output_fields = WorkflowExtractionFieldSerializer(
        many=True, help_text=f"The fields to fill, each with its own instruction. 1 to {MAX_FIELDS} fields."
    )

    def validate_context(self, value: Any) -> Any:
        return validate_workflow_context(value, input_name="the text to read")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not self.partial and attrs.get("context") is None and attrs.get("task_run_id") is None:
            raise serializers.ValidationError({"context": "Enter the text to read, or an AI task run to read."})
        return attrs

    def validate_output_fields(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        if not 1 <= len(value) <= MAX_FIELDS:
            raise serializers.ValidationError(f"Enter between 1 and {MAX_FIELDS} fields.")
        names = [field["name"] for field in value]
        if len(set(names)) != len(names):
            raise serializers.ValidationError("Give every field a different name.")
        return value


class WorkflowExtractionResponseSerializer(serializers.Serializer):
    values = serializers.DictField(
        child=serializers.JSONField(),
        help_text=f"Every field name mapped to its value: text of at most {MAX_TEXT_VALUE_CHARS} characters, a number, true or false, or null when the output does not state it.",
    )


class WorkflowExtractionErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the fields were not extracted.")


class WorkflowExtractionViewSet(viewsets.GenericViewSet):
    """Fill named fields from a workflow step's output with an AI model for the "Extract with AI" action.
    Authenticated by a scoped service JWT minted by the plugin server, never by a user credential."""

    authentication_classes = [WorkflowExtractJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowExtractionRequestSerializer

    @extend_schema(
        request=WorkflowExtractionRequestSerializer,
        responses={
            200: WorkflowExtractionResponseSerializer,
            403: OpenApiResponse(
                response=WorkflowExtractionErrorSerializer,
                description="The feature is disabled or the organization has not approved AI data processing",
            ),
            429: OpenApiResponse(
                response=WorkflowExtractionErrorSerializer,
                description="The project calls the model faster than its rate limit allows. Retry after the Retry-After seconds",
            ),
            501: OpenApiResponse(
                response=WorkflowExtractionErrorSerializer,
                description="This deployment has no AI gateway configured",
            ),
            422: OpenApiResponse(
                response=WorkflowExtractionErrorSerializer,
                description="The model refused the request or returned a value of the wrong type",
            ),
            503: OpenApiResponse(
                response=WorkflowExtractionErrorSerializer,
                description="The model is busy or unreachable. Retry later",
            ),
        },
        summary="Extract named fields from workflow step output with an AI model",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        user = cast(InternalAPIUser, request.user)
        team = Team.objects.select_related("organization").get(id=cast(int, user.current_team_id))

        if not gated_template_enabled("workflow-extract-action", team):
            return _error("Extract with AI is not enabled for this project.", status.HTTP_403_FORBIDDEN)

        serializer = WorkflowExtractionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not team.organization.is_ai_data_processing_approved:
            return _error(
                "Your organization has not approved AI data processing. Approve it in organization settings.",
                status.HTTP_403_FORBIDDEN,
            )

        hog_flow_id = str(cast(dict[str, Any], request.auth)["hog_flow_id"])
        context = data["context"]
        if data["task_run_id"] is not None:
            try:
                context = _task_report_context(team.id, UUID(hog_flow_id), data["task_run_id"])
            except _TaskReportUnreadable as error:
                return _error(str(error), status.HTTP_422_UNPROCESSABLE_ENTITY)

        fields = [
            ExtractionField(
                name=field["name"], type=ExtractionFieldType(field["type"]), instruction=field["instruction"]
            )
            for field in data["output_fields"]
        ]
        try:
            values = extract_fields(
                team_id=team.id,
                hog_flow_id=hog_flow_id,
                context=context,
                fields=fields,
            )
        except ExtractionBudgetExceededError as error:
            logger.info("workflow_extraction_budget_spent", team_id=team.id)
            response = _error(
                "Extract with AI is calling the model faster than this project's limit allows. "
                f"Try again in {error.retry_after} seconds, or trigger the step less often.",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = str(error.retry_after)
            return response
        except ExtractionUnavailableError:
            return _error("The model is not available on this PostHog deployment.", status.HTTP_501_NOT_IMPLEMENTED)
        except ExtractionModelBusyError:
            logger.warning("workflow_extraction_unreachable", team_id=team.id)
            return _error("The model is busy or unreachable. Retry later.", status.HTTP_503_SERVICE_UNAVAILABLE)
        except ExtractionModelRefusedError as error:
            logger.warning("workflow_extraction_refused", team_id=team.id, status_code=error.status_code)
            return _error(
                f"The model refused the request (gateway status {error.status_code}).",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except ExtractionUnusableError as error:
            logger.warning("workflow_extraction_unusable_answer", team_id=team.id)
            return _error(str(error), status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(WorkflowExtractionResponseSerializer({"values": values}).data)


class _TaskReportUnreadable(Exception):
    pass


def _task_report_context(team_id: int, hog_flow_id: UUID, run_id: UUID) -> dict[str, str]:
    report = get_workflow_task_run_final_message(team_id=team_id, hog_flow_id=hog_flow_id, run_id=run_id)
    if report is None:
        raise _TaskReportUnreadable(
            "This AI task run has no final message, or an AI task step in another workflow started it."
        )
    context = {"final_message": report}
    try:
        validate_workflow_context(context)
    except serializers.ValidationError:
        raise _TaskReportUnreadable(
            f"The AI task report is longer than the {MAX_CONTEXT_CHARS} characters this step reads."
        )
    return context


def _error(detail: str, http_status: int) -> Response:
    return Response(WorkflowExtractionErrorSerializer({"detail": detail}).data, status=http_status)
