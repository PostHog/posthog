from functools import partial
from typing import TYPE_CHECKING, Any, Optional

from django.db import models

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.event_usage import EventSource, report_user_action

from products.workflows.backend.facade.api import (
    MAX_WORKFLOW_CODE_BYTES,
    WorkflowCode,
    render_workflow_code,
    workflow_code_schema,
)
from products.workflows.backend.facade.contracts import WorkflowCodeRejected
from products.workflows.backend.facade.enums import (
    WORKFLOW_CODE_APPLY_RESULT_CHOICES,
    WORKFLOW_CODE_ERROR_STATUS_CHOICES,
    WORKFLOW_CODE_PLAN_RESULT_CHOICES,
    WORKFLOW_STATUS_CHOICES,
    WorkflowCodeApplyResult,
)

if TYPE_CHECKING:
    from products.workflows.backend.presentation.views.hog_flow import HogFlowViewSet

logger = structlog.get_logger(__name__)


class HogFlowCodeRequestSerializer(serializers.Serializer):
    content = serializers.CharField(
        trim_whitespace=False,
        allow_blank=True,
        help_text=(
            "The workflow file as text, in YAML, or in JSON when it starts with {. "
            f"At most {MAX_WORKFLOW_CODE_BYTES} bytes. Get its schema from the code_schema endpoint, "
            "or the workflows-get-code-schema MCP tool."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # The workflow serializer reads flags such as stage_draft from the raw request body, and a file is
        # the whole request, so nothing else may ride along.
        unknown = sorted(set(self.initial_data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                dict.fromkeys(unknown, "Send only content. Everything about the workflow goes in the file.")
            )
        return attrs


class HogFlowCodeErrorSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=WORKFLOW_CODE_ERROR_STATUS_CHOICES, help_text="A machine-readable code for the kind of mistake."
    )
    message = serializers.CharField(help_text="What is wrong, and where.")
    why = serializers.CharField(help_text="Why PostHog refuses it.")
    fix = serializers.CharField(help_text="What to change in the file.")
    path = serializers.CharField(
        allow_null=True,
        help_text="Where the mistake is, in the file's own field names, for example steps[1].arms[0].then[0].subject. Null when it concerns the whole file.",
    )
    line = serializers.IntegerField(
        allow_null=True, help_text="The 1-based line of the mistake. Null for JSON content and whole-file mistakes."
    )
    column = serializers.IntegerField(
        allow_null=True, help_text="The 1-based column of the mistake. Null for JSON content and whole-file mistakes."
    )


class HogFlowCodeErrorsSerializer(serializers.Serializer):
    errors = HogFlowCodeErrorSerializer(  # type: ignore[assignment]
        many=True, help_text="Every mistake in the file, in file order."
    )


class HogFlowCodeWorkflowSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The workflow id.")
    key = serializers.CharField(help_text="The key the file names.")
    name = serializers.CharField(allow_null=True, help_text="The stored workflow name.")
    version = serializers.IntegerField(help_text="The stored workflow version.")
    status = serializers.ChoiceField(choices=WORKFLOW_STATUS_CHOICES, help_text="The stored workflow status.")


class HogFlowCodeStepSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The step id.")
    name = serializers.CharField(help_text="The step name.")
    type = serializers.CharField(help_text="The action type the step compiles to, for example delay.")


class HogFlowCodeChangedStepSerializer(HogFlowCodeStepSerializer):
    changes = serializers.ListField(
        child=serializers.CharField(),
        help_text="The step's fields that change, as dotted paths at most two levels deep, for example config.conditions.",
    )


class HogFlowCodeStatusChangeSerializer(serializers.Serializer):
    to = serializers.ChoiceField(choices=WORKFLOW_STATUS_CHOICES, help_text="The status the file sets.")

    def get_fields(self) -> dict[str, serializers.Field]:
        # `from` is a Python keyword, so it cannot be a class attribute.
        fields = super().get_fields()
        fields["from"] = serializers.ChoiceField(
            choices=WORKFLOW_STATUS_CHOICES,
            allow_null=True,
            help_text="The stored status. Null when the file creates the workflow.",
        )
        return fields


class HogFlowCodePlanSerializer(serializers.Serializer):
    result = serializers.ChoiceField(
        choices=WORKFLOW_CODE_PLAN_RESULT_CHOICES,
        help_text=(
            "create: no workflow has this key. update: applying the file changes the workflow. "
            "stage: applying it through MCP stages the change as a draft of the active workflow, to publish with workflows-publish. "
            "unchanged: it changes nothing."
        ),
    )
    workflow = HogFlowCodeWorkflowSerializer(
        allow_null=True, help_text="The stored workflow with this key. Null when the file creates one."
    )
    changed_fields = serializers.ListField(
        child=serializers.CharField(),
        help_text="Workflow-level fields that change: name, description, exit_condition, variables, edges, trigger or exit.",
    )
    status = HogFlowCodeStatusChangeSerializer(help_text="The status before and after applying the file.")
    added_steps = HogFlowCodeStepSerializer(many=True, help_text="Steps the file adds.")
    changed_steps = HogFlowCodeChangedStepSerializer(many=True, help_text="Steps whose content changes.")
    in_flight_runs = serializers.IntegerField(
        allow_null=True, help_text="Runs in the workflow now. Null when PostHog could not count them."
    )
    position_unknown = serializers.IntegerField(
        allow_null=True, help_text="Runs whose current step is unknown. Null when PostHog could not count them."
    )
    discards_draft = serializers.BooleanField(
        help_text="True when the workflow has a staged draft that applying the file would throw away."
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        # The publish impact serializers live in hog_flow.py, which imports this module for the viewset's
        # base class, so they are imported when the fields are built rather than when this module loads.
        from products.workflows.backend.presentation.views.hog_flow import (  # noqa: PLC0415
            HogFlowPublishImpactDeletedStepSerializer,
            HogFlowPublishImpactEmptyVariableSerializer,
            HogFlowPublishImpactScheduleConflictSerializer,
        )

        fields = super().get_fields()
        fields["removed_steps"] = HogFlowPublishImpactDeletedStepSerializer(
            many=True, help_text="Steps the file removes, with the people in each and where they go."
        )
        fields["empty_variables"] = HogFlowPublishImpactEmptyVariableSerializer(
            many=True, help_text="Variables that are empty for runs that started before the step that sets them."
        )
        fields["schedule_conflicts"] = HogFlowPublishImpactScheduleConflictSerializer(
            many=True, help_text="Schedules that set variables the file removes."
        )
        return fields


class HogFlowCodeWarningSerializer(serializers.Serializer):
    message = serializers.CharField(help_text="What applying the file would do that needs attention.")
    fix = serializers.CharField(help_text="What to change if that is not what you want.")
    path = serializers.CharField(allow_null=True, help_text="Where in the file, when the warning concerns one place.")


class HogFlowCodeCheckResponseSerializer(serializers.Serializer):
    plan = HogFlowCodePlanSerializer(help_text="What applying the file would change.")
    warnings = HogFlowCodeWarningSerializer(many=True, help_text="Things to look at before applying the file.")


class HogFlowCodeApplyResponseSerializer(serializers.Serializer):
    result = serializers.ChoiceField(
        choices=WORKFLOW_CODE_APPLY_RESULT_CHOICES,
        help_text=(
            "created: the file made a new workflow. updated: it changed the workflow. "
            "staged: the change waits as a draft of the active workflow; publish it with workflows-publish. "
            "unchanged: nothing was written."
        ),
    )
    workflow = HogFlowCodeWorkflowSerializer(help_text="The workflow with this key, as stored after the apply.")
    plan = HogFlowCodePlanSerializer(help_text="What the apply changed, as code_check plans it.")
    warnings = HogFlowCodeWarningSerializer(many=True, help_text="Things to look at after the apply.")


class HogFlowCodeRenderWarningSerializer(serializers.Serializer):
    action_id = serializers.CharField(
        allow_null=True, help_text="The step the warning is about. Null when it concerns the whole workflow."
    )
    message = serializers.CharField(help_text="What the file leaves out or changes, and what applying it does.")


class HogFlowCodeResponseSerializer(serializers.Serializer):
    content = serializers.CharField(
        help_text="The live workflow as a YAML workflow file. Each warning also opens the file as a # comment line."
    )
    warnings = HogFlowCodeRenderWarningSerializer(
        many=True, help_text="Parts of the workflow the file cannot carry exactly. Empty when the file is exact."
    )


class HogFlowCodeMixin:
    """Workflows as code: the actions that read and check a workflow file on the workflows viewset."""

    @extend_schema(
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="The workflow file's JSON Schema.")}
    )
    @action(detail=False, methods=["GET"], pagination_class=None, filter_backends=[])
    def code_schema(self: "HogFlowViewSet", request: Request, **kwargs: Any) -> Response:
        """The JSON Schema of a workflow file (draft 2020-12). Every field carries a description."""
        _report_code_event(self, "hog_flow_code_schema_fetched", {})
        return Response(workflow_code_schema())

    @extend_schema(
        request=HogFlowCodeRequestSerializer,
        responses={200: HogFlowCodeCheckResponseSerializer, 400: HogFlowCodeErrorsSerializer},
    )
    @action(detail=False, methods=["POST"], pagination_class=None, filter_backends=[])
    def code_check(self: "HogFlowViewSet", request: Request, **kwargs: Any) -> Response:
        """Check a workflow file and plan what applying it would change. Writes nothing."""
        body = HogFlowCodeRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            checked = _workflow_code(self).check(body.validated_data["content"])
        except WorkflowCodeRejected as rejected:
            _report_code_event(
                self, "hog_flow_code_checked", {"result": "invalid", "errors_count": len(rejected.errors)}
            )
            return Response(_errors(rejected), status=status.HTTP_400_BAD_REQUEST)
        plan = checked.plan
        _report_code_event(
            self,
            "hog_flow_code_checked",
            {"result": plan.result, "errors_count": 0},
            workflow_id=plan.workflow.id if plan.workflow else None,
            workflow_name=plan.workflow.name if plan.workflow else None,
        )
        return Response(HogFlowCodeCheckResponseSerializer({"plan": plan, "warnings": checked.warnings}).data)

    @extend_schema(responses={200: HogFlowCodeResponseSerializer})
    @action(detail=True, methods=["GET"], pagination_class=None, filter_backends=[])
    def code(self: "HogFlowViewSet", request: Request, **kwargs: Any) -> Response:
        """The live workflow as a YAML workflow file that code_check accepts, with warnings for what it cannot carry."""
        workflow = self.get_object()
        rendered = render_workflow_code(self.get_serializer(workflow).data, key=workflow.key)
        _report_code_event(
            self,
            "hog_flow_code_pulled",
            {"warnings_count": len(rendered.warnings)},
            workflow_id=str(workflow.id),
            workflow_name=workflow.name,
        )
        return Response(HogFlowCodeResponseSerializer(rendered).data)

    @extend_schema(
        request=HogFlowCodeRequestSerializer,
        responses={
            200: HogFlowCodeApplyResponseSerializer,
            201: HogFlowCodeApplyResponseSerializer,
            400: HogFlowCodeErrorsSerializer,
            409: HogFlowCodeErrorsSerializer,
        },
    )
    @action(detail=False, methods=["POST"], pagination_class=None, filter_backends=[])
    def code_apply(self: "HogFlowViewSet", request: Request, **kwargs: Any) -> Response:
        """Create the workflow a file describes, or update the one with its key. Writes nothing when the file matches."""
        body = HogFlowCodeRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            applied = _workflow_code(self).apply(body.validated_data["content"])
        except WorkflowCodeRejected as rejected:
            _report_code_event(
                self, "hog_flow_code_applied", {"result": "invalid", "errors_count": len(rejected.errors)}
            )
            return Response(
                _errors(rejected),
                status=status.HTTP_409_CONFLICT if rejected.is_conflict else status.HTTP_400_BAD_REQUEST,
            )
        plan = applied.plan
        _report_code_event(
            self,
            "hog_flow_code_applied",
            {"result": applied.result, "added_steps": len(plan.added_steps), "removed_steps": len(plan.removed_steps)},
            workflow_id=applied.workflow.id,
            workflow_name=applied.workflow.name,
        )
        response = HogFlowCodeApplyResponseSerializer(
            {"result": applied.result, "workflow": applied.workflow, "plan": plan, "warnings": applied.warnings}
        )
        created = applied.result == WorkflowCodeApplyResult.CREATED
        return Response(response.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


def _workflow_code(view: "HogFlowViewSet") -> WorkflowCode:
    return WorkflowCode(
        team_id=view.team_id,
        access=view.user_access_control,
        writer=view._workflow_writer(),
        through_mcp=view._is_mcp_request(view.request),
        validate_definition=partial(_validate_definition, view),
        count_in_flight=view._get_in_flight_counts,
        report_usage=view._report_workflow_action,
    )


def _validate_definition(
    view: "HogFlowViewSet", workflow: Optional[models.Model], definition: dict[str, Any]
) -> serializers.BaseSerializer:
    serializer = view.get_serializer(workflow, data=definition)
    serializer.context["enforce_graph_structure"] = True
    # A file is authored as code whoever sends it, so it is validated as strictly as an API write. The web
    # builder's lenient draft rules would let a file through that the same file sent by CI would fail.
    if serializer.context.get("event_source") == EventSource.WEB:
        serializer.context["event_source"] = EventSource.API
    serializer.is_valid(raise_exception=True)
    return serializer


def _errors(rejected: WorkflowCodeRejected) -> dict[str, Any]:
    return HogFlowCodeErrorsSerializer({"errors": rejected.errors}).data


def _report_code_event(
    view: "HogFlowViewSet",
    event: str,
    properties: dict[str, Any],
    *,
    workflow_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
) -> None:
    # Capture must never fail the request. report_user_action adds the event source from the request, so
    # MCP, API and CI use stay apart.
    workflow_properties = {"workflow_id": workflow_id, "workflow_name": workflow_name} if workflow_id else {}
    try:
        report_user_action(
            view.request.user,
            event,
            {
                "team_id": str(view.team_id),
                "organization_id": str(view.organization.id),
                **workflow_properties,
                **properties,
            },
            team=view.team,
            request=view.request,
        )
    except Exception as e:
        logger.warning("Failed to capture workflow code usage event", event=event, error=str(e))
