from copy import deepcopy
from functools import cache
from typing import TYPE_CHECKING, Any, Optional

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource, report_user_action

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
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
    WorkflowCodePlanResult,
    WorkflowState,
    WorkflowSummary,
    plan_create,
    plan_update,
    plan_warnings,
)
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
        help_text="create: no workflow has this key. update: applying the file changes the workflow. unchanged: it changes nothing.",
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


def _plan(view: "HogFlowViewSet", loaded: LoadedContent) -> tuple[Optional[HogFlow], CodePlan]:
    compiled, key = _compile(loaded)
    workflow = _find_workflow(view, key)
    validated = _validate_definition(view, compiled, workflow).validated_data
    if workflow is None:
        return None, plan_create(_state(validated, content=validated))
    contents = _comparable_contents(workflow, validated)
    counts = view._get_in_flight_counts(workflow)
    impact = _publish_impact(workflow, validated, counts)
    plan = plan_update(
        workflow=WorkflowSummary(
            id=str(workflow.id),
            key=key,
            name=workflow.name,
            version=workflow.version,
            status=workflow.status,
        ),
        stored=WorkflowState(
            name=workflow.name or "",
            description=workflow.description,
            status=workflow.status,
            content=contents.stored,
        ),
        proposed=_state(validated, content=contents.proposed),
        impact=impact,
        in_flight_runs=counts.get("count") if counts else None,
        has_draft=workflow.draft is not None,
    )
    return workflow, plan


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


def _find_workflow(view: "HogFlowViewSet", key: str) -> Optional[HogFlow]:
    workflow = HogFlow.objects.filter(team_id=view.team_id, key=key).first()
    # The viewset's access filter applies to list only, so a lookup by key checks the object itself.
    if workflow is not None and not view.user_access_control.check_access_level_for_object(
        workflow, required_level="viewer"
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


@frozen
class _ComparableContents:
    stored: dict[str, Any]
    proposed: dict[str, Any]


def _comparable_contents(workflow: HogFlow, validated: dict[str, Any]) -> _ComparableContents:
    """The stored content and the content the file would store, normalized as _stage_revision_bump does.

    Stored bytecode, secrets and the wrapped email design then compare equal, so a matching file is unchanged.
    """
    # hog_flow.py imports this module for the viewset's base class, so its helpers are imported at call time.
    from products.workflows.backend.presentation.views.hog_flow import (  # noqa: PLC0415
        DRAFT_CONTENT_FIELDS,
        TemplateCache,
        _without_bytecode_contracts,
        snapshot_flow_content,
        strip_content_secrets,
    )

    stored = snapshot_flow_content(workflow)
    proposed = {**stored, **{field: validated[field] for field in DRAFT_CONTENT_FIELDS if field in validated}}
    template_cache: TemplateCache = {}
    return _ComparableContents(
        stored=_without_bytecode_contracts(strip_content_secrets(stored, template_cache)),
        proposed=_without_bytecode_contracts(strip_content_secrets(proposed, template_cache)),
    )


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
