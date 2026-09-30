from copy import deepcopy
from functools import cache
from typing import TYPE_CHECKING, Any, Optional

from django.db import IntegrityError, transaction

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource, report_user_action

from products.access_control.backend.facade.user_access_control import AccessControlLevel
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.facade.api import comparable_workflow_contents
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.presentation.views.publish_impact import build_publish_impact
from products.workflows.backend.services.workflow_code.compiler import (
    CompiledWorkflow,
    FunctionTemplate,
    compile_document,
    definition_errors,
    template_errors,
    with_stored_editor_fields,
)
from products.workflows.backend.services.workflow_code.errors import (
    DocumentError,
    DocumentInvalid,
    WorkflowCodeErrorStatus,
    format_path,
)
from products.workflows.backend.services.workflow_code.plan import (
    CodePlan,
    WorkflowCodeApplyResult,
    WorkflowCodePlanResult,
    WorkflowState,
    WorkflowSummary,
    plan_create,
    plan_stage,
    plan_update,
    plan_warnings,
)
from products.workflows.backend.services.workflow_code.renderer import render_workflow
from products.workflows.backend.services.workflow_code.schema import validate_document, workflow_document_schema
from products.workflows.backend.services.workflow_code.yaml_loader import MAX_CONTENT_BYTES, LoadedContent, load_content

if TYPE_CHECKING:
    from products.workflows.backend.presentation.views.hog_flow import HogFlowViewSet

logger = structlog.get_logger(__name__)


class HogFlowCodeRequestSerializer(serializers.Serializer):
    content = serializers.CharField(
        trim_whitespace=False,
        allow_blank=True,
        help_text=(
            "The workflow file as text, in YAML, or in JSON when it starts with {. "
            f"At most {MAX_CONTENT_BYTES} bytes. Get its schema from code_schema."
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
        choices=WorkflowCodeErrorStatus.choices, help_text="A machine-readable code for the kind of mistake."
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
    status = serializers.ChoiceField(choices=HogFlow.State.choices, help_text="The stored workflow status.")


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
    to = serializers.ChoiceField(choices=HogFlow.State.choices, help_text="The status the file sets.")

    def get_fields(self) -> dict[str, serializers.Field]:
        # `from` is a Python keyword, so it cannot be a class attribute.
        fields = super().get_fields()
        fields["from"] = serializers.ChoiceField(
            choices=HogFlow.State.choices,
            allow_null=True,
            help_text="The stored status. Null when the file creates the workflow.",
        )
        return fields


class HogFlowCodePlanSerializer(serializers.Serializer):
    result = serializers.ChoiceField(
        choices=WorkflowCodePlanResult.choices,
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
        choices=WorkflowCodeApplyResult.choices,
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
        _report_code_event(self, "hog_flow_code_schema_fetched", None, {})
        return Response(workflow_document_schema())

    @extend_schema(
        request=HogFlowCodeRequestSerializer,
        responses={200: HogFlowCodeCheckResponseSerializer, 400: HogFlowCodeErrorsSerializer},
    )
    @action(detail=False, methods=["POST"], pagination_class=None, filter_backends=[])
    def code_check(self: "HogFlowViewSet", request: Request, **kwargs: Any) -> Response:
        """Check a workflow file and plan what applying it would change. Writes nothing."""
        body = HogFlowCodeRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        loaded: Optional[LoadedContent] = None
        try:
            loaded = load_content(body.validated_data["content"])
            workflow, plan = _plan(self, loaded)
        except DocumentInvalid as invalid:
            _report_code_event(
                self, "hog_flow_code_checked", None, {"result": "invalid", "errors_count": len(invalid.errors)}
            )
            return Response(
                HogFlowCodeErrorsSerializer({"errors": _located(invalid.errors, loaded)}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        _report_code_event(self, "hog_flow_code_checked", workflow, {"result": plan.result, "errors_count": 0})
        return Response(HogFlowCodeCheckResponseSerializer({"plan": plan, "warnings": plan_warnings(plan)}).data)

    @extend_schema(responses={200: HogFlowCodeResponseSerializer})
    @action(detail=True, methods=["GET"], pagination_class=None, filter_backends=[])
    def code(self: "HogFlowViewSet", request: Request, **kwargs: Any) -> Response:
        """The live workflow as a YAML workflow file that code_check accepts, with warnings for what it cannot carry."""
        workflow = self.get_object()
        rendered = render_workflow(self.get_serializer(workflow).data, key=workflow.key)
        _report_code_event(self, "hog_flow_code_pulled", workflow, {"warnings_count": len(rendered.warnings)})
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
        loaded: Optional[LoadedContent] = None
        try:
            loaded = load_content(body.validated_data["content"])
            applied = _apply(self, loaded)
        except DocumentInvalid as invalid:
            _report_code_event(
                self, "hog_flow_code_applied", None, {"result": "invalid", "errors_count": len(invalid.errors)}
            )
            conflict = any(error.status == WorkflowCodeErrorStatus.CONFLICT for error in invalid.errors)
            return Response(
                HogFlowCodeErrorsSerializer({"errors": _located(invalid.errors, loaded)}).data,
                status=status.HTTP_409_CONFLICT if conflict else status.HTTP_400_BAD_REQUEST,
            )
        plan = applied.plan
        _report_code_event(
            self,
            "hog_flow_code_applied",
            applied.workflow,
            {"result": applied.result, "added_steps": len(plan.added_steps), "removed_steps": len(plan.removed_steps)},
        )
        response = HogFlowCodeApplyResponseSerializer(
            {
                "result": applied.result,
                "workflow": _summary(applied.workflow, applied.key),
                "plan": plan,
                "warnings": plan_warnings(plan),
            }
        )
        created = applied.result == WorkflowCodeApplyResult.CREATED
        return Response(response.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@frozen
class _Applied:
    result: WorkflowCodeApplyResult
    key: str
    workflow: HogFlow
    plan: CodePlan


def _plan(view: "HogFlowViewSet", loaded: LoadedContent) -> tuple[Optional[HogFlow], CodePlan]:
    compiled, key = _compile(loaded)
    workflow = _find_workflow(view, key, required_level="viewer")
    validated = _validate_definition(view, compiled, workflow).validated_data
    if workflow is None:
        plan = plan_create(_state(validated, content=validated))
    else:
        counts = view._get_in_flight_counts(workflow)
        plan = _plan_update(key, workflow, validated, counts, staged=_stages_active_content(view, workflow))
    _refuse_status_change_through_mcp(view, plan)
    return workflow, plan


def _apply(view: "HogFlowViewSet", loaded: LoadedContent) -> _Applied:
    compiled, key = _compile(loaded)
    workflow = _find_workflow(view, key, required_level="editor")
    if workflow is None:
        return _create(view, compiled, key)
    return _update(view, compiled, key, workflow)


def _create(view: "HogFlowViewSet", compiled: CompiledWorkflow, key: str) -> _Applied:
    # The viewset's permission class checks the resource-level editor role only for its own create action.
    if not view.user_access_control.check_access_level_for_resource("hog_flow", required_level="editor"):
        raise exceptions.PermissionDenied("You don't have access to create workflows in this project.")
    serializer = _validate_definition(view, compiled, None)
    plan = plan_create(_state(serializer.validated_data, content=serializer.validated_data))
    _refuse_status_change_through_mcp(view, plan)
    try:
        # A savepoint, so a lost race on the key leaves the request's transaction usable.
        with transaction.atomic():
            workflow = view._workflow_writer().create(serializer, key=key)
    except IntegrityError as error:
        if _KEY_CONSTRAINT not in str(error):
            raise
        raise DocumentInvalid([_key_conflict(key)])
    view._report_workflow_action(
        "hog_flow_created",
        workflow,
        {"edges_count": len(workflow.edges or []), "actions_count": len(workflow.actions or [])},
    )
    return _Applied(result=WorkflowCodeApplyResult.CREATED, key=key, workflow=workflow, plan=plan)


def _update(view: "HogFlowViewSet", compiled: CompiledWorkflow, key: str, workflow: HogFlow) -> _Applied:
    # The counting service is a network call, so it runs before the row lock rather than while holding it.
    counts = view._get_in_flight_counts(workflow)
    plans: list[CodePlan] = []

    def validate(locked: HogFlow, stored: HogFlow, staged: bool) -> Optional[serializers.BaseSerializer]:
        serializer = _validate_definition(view, compiled, locked)
        plan = _plan_update(key, stored, serializer.validated_data, counts, staged=staged)
        _refuse_status_change_through_mcp(view, plan)
        plans.append(plan)
        return None if plan.result == WorkflowCodePlanResult.UNCHANGED else serializer

    try:
        written = view._workflow_writer().replace_content(
            workflow, validate, stage_active=view._is_mcp_request(view.request)
        )
    except HogFlow.DoesNotExist:
        raise DocumentInvalid([_key_conflict(key)])
    [plan] = plans
    if written is None:
        return _Applied(result=WorkflowCodeApplyResult.UNCHANGED, key=key, workflow=workflow, plan=plan)
    if plan.result == WorkflowCodePlanResult.STAGE:
        return _Applied(result=WorkflowCodeApplyResult.STAGED, key=key, workflow=written, plan=plan)
    if plan.status["from"] == HogFlow.State.DRAFT and written.status == HogFlow.State.ACTIVE:
        view._report_workflow_action(
            "hog_flow_activated",
            written,
            {"edges_count": len(written.edges or []), "actions_count": len(written.actions or [])},
        )
    return _Applied(result=WorkflowCodeApplyResult.UPDATED, key=key, workflow=written, plan=plan)


def _stages_active_content(view: "HogFlowViewSet", workflow: HogFlow) -> bool:
    # Through MCP, publish and its confirm token stay the only way content goes live on an active workflow.
    return view._workflow_writer().stages_as_draft(workflow, stage_active=view._is_mcp_request(view.request))


def _plan_update(
    key: str, workflow: HogFlow, validated: dict[str, Any], counts: Optional[dict[str, Any]], *, staged: bool
) -> CodePlan:
    live = comparable_workflow_contents(workflow, validated, with_draft=False)
    plan = plan_update(
        workflow=_summary(workflow, key),
        stored=_stored_state(workflow, live.stored),
        proposed=_state(validated, content=live.proposed),
        impact=_publish_impact(workflow, validated, counts),
        in_flight_runs=counts.get("count") if counts else None,
        has_draft=workflow.draft is not None,
    )
    if not staged:
        return plan
    target = comparable_workflow_contents(workflow, validated, with_draft=True)
    return plan_stage(
        plan,
        staged=_stored_state(workflow, target.stored),
        proposed=_state(validated, content=target.proposed),
        has_draft=workflow.draft is not None,
    )


def _summary(workflow: HogFlow, key: str) -> WorkflowSummary:
    return WorkflowSummary(
        id=str(workflow.id), key=key, name=workflow.name, version=workflow.version, status=workflow.status
    )


def _stored_state(workflow: HogFlow, content: dict[str, Any]) -> WorkflowState:
    return WorkflowState(
        name=workflow.name or "", description=workflow.description, status=workflow.status, content=content
    )


def _refuse_status_change_through_mcp(view: "HogFlowViewSet", plan: CodePlan) -> None:
    stored, proposed = plan.status["from"], plan.status["to"]
    if not view._is_mcp_request(view.request) or stored == proposed:
        return
    if stored is None and proposed != HogFlow.State.ACTIVE:
        return
    raise DocumentInvalid([_status_change_not_allowed(stored, proposed)])


def _status_change_not_allowed(stored: Optional[str], proposed: Optional[str]) -> DocumentError:
    if stored is None:
        message = "status is active, and a file sent through MCP cannot create an active workflow."
        fix = "Set status to draft and apply the file. Then turn the workflow on with workflows-enable."
    elif stored in (HogFlow.State.DRAFT, HogFlow.State.ACTIVE):
        message = (
            f"status is {proposed}, and the workflow is {stored}. A file sent through MCP cannot change the status."
        )
        fix = f"Set status to {stored} in the file. To turn the workflow on or off, use workflows-enable or workflows-disable."
    else:
        message = f"The workflow is {stored}, and a file sent through MCP cannot change the status."
        fix = "Ask a person to restore the workflow in PostHog first, then apply the file again."
    return DocumentError(
        status=WorkflowCodeErrorStatus.STATUS_CHANGE_NOT_ALLOWED,
        message=message,
        why="An agent turns a workflow on or off only with the tools made for that, so each change of status is a step of its own.",
        fix=fix,
        path=("status",),
    )


_KEY_CONSTRAINT = "unique_key_for_team"


def _key_conflict(key: str) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.CONFLICT,
        message=f"Another request created or deleted the workflow with the key {key} while this file was applied.",
        why="A key names one workflow in the project, and it changed hands during the apply, so PostHog wrote nothing from this file.",
        fix="Apply the file again. PostHog then updates the workflow with this key.",
        path=("key",),
    )


def _state(validated: dict[str, Any], content: dict[str, Any]) -> WorkflowState:
    return WorkflowState(
        name=validated.get("name") or "",
        description=validated.get("description", ""),
        status=validated["status"],
        content=content,
    )


def _compile(loaded: LoadedContent) -> tuple[CompiledWorkflow, str]:
    try:
        document = validate_document(loaded.data, loaded.scalar_sources)
    except DocumentInvalid as invalid:
        raise DocumentInvalid(loaded.with_validation_errors(invalid.errors))
    if loaded.errors:
        raise DocumentInvalid(loaded.errors)
    compiled = compile_document(document)
    errors = template_errors(compiled, cache(_get_template))
    if errors:
        raise DocumentInvalid(errors)
    return compiled, document.key


def _get_template(template_id: str) -> Optional[FunctionTemplate]:
    return HogFunctionTemplate.get_template(template_id)


def _find_workflow(view: "HogFlowViewSet", key: str, *, required_level: AccessControlLevel) -> Optional[HogFlow]:
    workflow = HogFlow.objects.filter(team_id=view.team_id, key=key).first()
    # The viewset's access filter applies to list only, so a lookup by key checks the object itself.
    if workflow is not None and not view.user_access_control.check_access_level_for_object(
        workflow, required_level=required_level
    ):
        raise exceptions.PermissionDenied("You don't have access to the workflow with this key.")
    return workflow


def _validate_definition(
    view: "HogFlowViewSet", compiled: CompiledWorkflow, workflow: Optional[HogFlow]
) -> serializers.BaseSerializer:
    definition = with_stored_editor_fields(compiled.definition, (workflow.actions or []) if workflow else [])
    # Validation writes nothing, but it changes the dicts it is given, so it gets a copy.
    serializer = view.get_serializer(workflow, data=deepcopy(definition))
    serializer.context["enforce_graph_structure"] = True
    # A file is authored as code whoever sends it, so it is validated as strictly as an API write. The web
    # builder's lenient draft rules would let a file through that the same file sent by CI would fail.
    if serializer.context.get("event_source") == EventSource.WEB:
        serializer.context["event_source"] = EventSource.API
    try:
        serializer.is_valid(raise_exception=True)
    except serializers.ValidationError as error:
        raise DocumentInvalid(definition_errors(error.detail, compiled))
    return serializer


def _publish_impact(workflow: HogFlow, validated: dict[str, Any], counts: Optional[dict[str, Any]]) -> dict[str, Any]:
    schedule_overrides = {
        str(schedule_id): variables or {}
        for schedule_id, variables in workflow.schedules.exclude(status=HogFlowSchedule.Status.COMPLETED).values_list(
            "id", "variables"
        )
    }
    return build_publish_impact(
        live_actions=workflow.actions or [],
        live_edges=workflow.edges or [],
        live_variables=workflow.variables or [],
        draft_actions=validated["actions"],
        draft_variables=validated.get("variables") or [],
        existing_redirects=workflow.action_redirects,
        by_action_counts=counts.get("by_action") if counts else None,
        position_unknown=counts.get("position_unknown") if counts else None,
        schedule_overrides=schedule_overrides,
    )


def _located(errors: list[DocumentError], loaded: Optional[LoadedContent]) -> list[dict[str, Any]]:
    located = []
    for error in errors:
        position = loaded.locate(error) if loaded is not None else None
        located.append(
            {
                "status": error.status,
                "message": error.message,
                "why": error.why,
                "fix": error.fix,
                "path": format_path(error.path),
                "line": position.line if position else None,
                "column": position.column if position else None,
            }
        )
    return sorted(located, key=lambda e: (e["line"] is None, e["line"] or 0, e["column"] or 0))


def _report_code_event(
    view: "HogFlowViewSet", event: str, workflow: Optional[HogFlow], properties: dict[str, Any]
) -> None:
    # Capture must never fail the request. report_user_action adds the event source from the request, so
    # MCP, API and CI use stay apart.
    workflow_properties = {"workflow_id": str(workflow.id), "workflow_name": workflow.name} if workflow else {}
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
