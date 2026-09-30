from collections.abc import Callable
from copy import deepcopy
from functools import cache, partial
from typing import Any, Optional

from django.db import IntegrityError, transaction

from rest_framework import exceptions, serializers

from posthog.dataclasses import frozen
from posthog.models.integration import Integration

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.facade.contracts import WorkflowCodeError, WorkflowCodeRejected
from products.workflows.backend.facade.enums import (
    WorkflowCodeApplyResult,
    WorkflowCodeErrorStatus,
    WorkflowCodePlanResult,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.services.publish_impact import build_publish_impact
from products.workflows.backend.services.workflow_code.compiler import (
    CompiledWorkflow,
    FunctionTemplate,
    compile_document,
    definition_errors,
    sender_errors,
    template_errors,
    with_stored_editor_fields,
)
from products.workflows.backend.services.workflow_code.errors import DocumentError, DocumentInvalid, format_path
from products.workflows.backend.services.workflow_code.plan import (
    CodePlan,
    PlanWarning,
    WorkflowState,
    WorkflowSummary,
    plan_create,
    plan_stage,
    plan_update,
    plan_warnings,
)
from products.workflows.backend.services.workflow_code.schema import validate_document
from products.workflows.backend.services.workflow_code.yaml_loader import LoadedContent, load_content
from products.workflows.backend.services.workflow_writes import (
    ValidatedWorkflow,
    WorkflowUsageReporter,
    WorkflowWriter,
    comparable_contents,
)

# Validates a compiled definition as the workflows API would, against the stored workflow when there is
# one, and raises serializers.ValidationError when it refuses it.
DefinitionValidator = Callable[[Optional[HogFlow], dict[str, Any]], ValidatedWorkflow]
InFlightCounter = Callable[[HogFlow], Optional[dict[str, Any]]]

_KEY_CONSTRAINT = "unique_key_for_team"
MAX_REPORTED_ERRORS = 50


@frozen
class WorkflowCodeChecked:
    plan: CodePlan
    warnings: list[PlanWarning]


@frozen
class WorkflowCodeApplied:
    result: WorkflowCodeApplyResult
    workflow: WorkflowSummary
    plan: CodePlan
    warnings: list[PlanWarning]


class WorkflowCode:
    """Checks and applies workflow files for one team, acting for one caller.

    Every refusal raises `WorkflowCodeRejected` with each error placed in the file, and writes nothing.
    """

    def __init__(
        self,
        *,
        team_id: int,
        access: UserAccessControl,
        writer: WorkflowWriter,
        through_mcp: bool,
        validate_definition: DefinitionValidator,
        count_in_flight: InFlightCounter,
        report_usage: WorkflowUsageReporter,
    ) -> None:
        self._team_id = team_id
        self._access = access
        self._writer = writer
        self._through_mcp = through_mcp
        self._validate_definition = validate_definition
        self._count_in_flight = count_in_flight
        self._report_usage = report_usage

    def check(self, content: str) -> WorkflowCodeChecked:
        """Plan what applying the file would change. Writes nothing."""
        loaded: Optional[LoadedContent] = None
        try:
            loaded = load_content(content)
            plan = self._plan(loaded)
        except DocumentInvalid as invalid:
            raise _rejected(invalid, loaded) from invalid
        return WorkflowCodeChecked(plan=plan, warnings=plan_warnings(plan))

    def apply(self, content: str) -> WorkflowCodeApplied:
        """Create the workflow the file describes, or update the one with its key."""
        loaded: Optional[LoadedContent] = None
        try:
            loaded = load_content(content)
            return self._apply(loaded)
        except DocumentInvalid as invalid:
            raise _rejected(invalid, loaded) from invalid

    def _plan(self, loaded: LoadedContent) -> CodePlan:
        compiled, key = _compile(loaded, self._team_id)
        workflow = self._find_workflow(key, required_level="viewer")
        _refuse_archived(workflow, compiled, key)
        validated = self._validated(compiled, workflow).validated_data
        if workflow is None:
            plan = plan_create(_state(validated, content=validated))
        else:
            plan, _counts = self._plan_existing(key, workflow, validated)
        self._refuse_disallowed_status(plan, key)
        return plan

    def _plan_existing(
        self, key: str, workflow: HogFlow, validated: dict[str, Any]
    ) -> tuple[CodePlan, Optional[dict[str, Any]]]:
        """The plan for a stored workflow, and the in-flight counts behind it.

        Counting is a network call, and most files in a repository change nothing on a given run, so an
        unchanged plan skips it.
        """
        staged = self._stages_active_content(workflow)
        plan = _plan_update(key, workflow, validated, None, staged=staged)
        if plan.result == WorkflowCodePlanResult.UNCHANGED:
            return plan, None
        counts = self._count_in_flight(workflow)
        return _plan_update(key, workflow, validated, counts, staged=staged), counts

    def _apply(self, loaded: LoadedContent) -> WorkflowCodeApplied:
        compiled, key = _compile(loaded, self._team_id)
        workflow = self._find_workflow(key, required_level="editor")
        _refuse_archived(workflow, compiled, key)
        if workflow is None:
            return self._create(compiled, key)
        return self._update(compiled, key, workflow)

    def _create(self, compiled: CompiledWorkflow, key: str) -> WorkflowCodeApplied:
        # The viewset's permission class checks the resource-level editor role only for its own create action.
        if not self._access.check_access_level_for_resource("hog_flow", required_level="editor"):
            raise exceptions.PermissionDenied("You don't have access to create workflows in this project.")
        validated = self._validated(compiled, None)
        plan = plan_create(_state(validated.validated_data, content=validated.validated_data))
        self._refuse_disallowed_status(plan, key)
        try:
            # A savepoint, so a lost race on the key leaves the request's transaction usable.
            with transaction.atomic():
                workflow = self._writer.create(validated, key=key)
        except IntegrityError as error:
            if _KEY_CONSTRAINT not in str(error):
                raise
            raise DocumentInvalid([_key_conflict(key)])
        self._report_usage(
            "hog_flow_created",
            workflow,
            {"edges_count": len(workflow.edges or []), "actions_count": len(workflow.actions or [])},
        )
        return _applied(WorkflowCodeApplyResult.CREATED, key, workflow, plan)

    def _update(self, compiled: CompiledWorkflow, key: str, workflow: HogFlow) -> WorkflowCodeApplied:
        # Planned before the row lock, so the counting service's network call never runs while holding it.
        plan, counts = self._plan_existing(key, workflow, self._validated(compiled, workflow).validated_data)
        self._refuse_disallowed_status(plan, key)
        if plan.result == WorkflowCodePlanResult.UNCHANGED:
            return _applied(WorkflowCodeApplyResult.UNCHANGED, key, workflow, plan)
        plans: list[CodePlan] = []

        def validate(locked: HogFlow, stored: HogFlow, staged: bool) -> Optional[ValidatedWorkflow]:
            validated = self._validated(compiled, locked)
            plan = _plan_update(key, stored, validated.validated_data, counts, staged=staged)
            self._refuse_disallowed_status(plan, key)
            plans.append(plan)
            return None if plan.result == WorkflowCodePlanResult.UNCHANGED else validated

        try:
            written = self._writer.replace_content(workflow, validate, stage_active=self._through_mcp)
        except HogFlow.DoesNotExist:
            raise DocumentInvalid([_key_conflict(key)])
        [plan] = plans
        if written is None:
            return _applied(WorkflowCodeApplyResult.UNCHANGED, key, workflow, plan)
        if plan.result == WorkflowCodePlanResult.STAGE:
            return _applied(WorkflowCodeApplyResult.STAGED, key, written, plan)
        if plan.status["from"] == HogFlow.State.DRAFT and written.status == HogFlow.State.ACTIVE:
            self._report_usage(
                "hog_flow_activated",
                written,
                {"edges_count": len(written.edges or []), "actions_count": len(written.actions or [])},
            )
        return _applied(WorkflowCodeApplyResult.UPDATED, key, written, plan)

    def _stages_active_content(self, workflow: HogFlow) -> bool:
        # Through MCP, publish and its confirm token stay the only way content goes live on an active workflow.
        return self._writer.stages_as_draft(workflow, stage_active=self._through_mcp)

    def _refuse_disallowed_status(self, plan: CodePlan, key: str) -> None:
        stored, proposed = plan.status["from"], plan.status["to"]
        # Checked again here because the workflow may be archived after it was looked up.
        if stored == HogFlow.State.ARCHIVED:
            raise DocumentInvalid([_workflow_archived(key, proposed)])
        if not self._through_mcp or stored == proposed:
            return
        if stored is None and proposed != HogFlow.State.ACTIVE:
            return
        raise DocumentInvalid([_status_change_not_allowed(stored, proposed)])

    def _find_workflow(self, key: str, *, required_level: AccessControlLevel) -> Optional[HogFlow]:
        workflow = HogFlow.objects.filter(team_id=self._team_id, key=key).first()
        # The viewset's access filter applies to list only, so a lookup by key checks the object itself.
        if workflow is not None and not self._access.check_access_level_for_object(
            workflow, required_level=required_level
        ):
            raise exceptions.PermissionDenied("You don't have access to the workflow with this key.")
        return workflow

    def _validated(self, compiled: CompiledWorkflow, workflow: Optional[HogFlow]) -> ValidatedWorkflow:
        definition = with_stored_editor_fields(compiled.definition, (workflow.actions or []) if workflow else [])
        try:
            # Validation writes nothing, but it changes the dicts it is given, so it gets a copy.
            return self._validate_definition(workflow, deepcopy(definition))
        except serializers.ValidationError as error:
            raise DocumentInvalid(definition_errors(error.detail, compiled))


def _applied(result: WorkflowCodeApplyResult, key: str, workflow: HogFlow, plan: CodePlan) -> WorkflowCodeApplied:
    return WorkflowCodeApplied(result=result, workflow=_summary(workflow, key), plan=plan, warnings=plan_warnings(plan))


def _plan_update(
    key: str, workflow: HogFlow, validated: dict[str, Any], counts: Optional[dict[str, Any]], *, staged: bool
) -> CodePlan:
    live = comparable_contents(workflow, validated, with_draft=False)
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
    target = comparable_contents(workflow, validated, with_draft=True)
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


def _state(validated: dict[str, Any], content: dict[str, Any]) -> WorkflowState:
    return WorkflowState(
        name=validated.get("name") or "",
        description=validated.get("description", ""),
        status=validated["status"],
        content=content,
    )


def _status_change_not_allowed(stored: Optional[str], proposed: Optional[str]) -> DocumentError:
    if stored is None:
        message = "status is active, and a file sent through MCP cannot create an active workflow."
        fix = "Set status to draft and apply the file. Then turn the workflow on with workflows-enable."
    else:
        message = (
            f"status is {proposed}, and the workflow is {stored}. A file sent through MCP cannot change the status."
        )
        fix = (
            f"Set status to {stored} in the file. To turn the workflow on, use workflows-enable. "
            "To turn it off, ask the user to do it in PostHog."
        )
    return DocumentError(
        status=WorkflowCodeErrorStatus.STATUS_CHANGE_NOT_ALLOWED,
        message=message,
        why="An agent changes a workflow's status only with the tools made for that, such as workflows-enable, so each change of status is a step of its own.",
        fix=fix,
        path=("status",),
    )


def _refuse_archived(workflow: Optional[HogFlow], compiled: CompiledWorkflow, key: str) -> None:
    # Before validation, so the author learns first that the file cannot apply at all.
    if workflow is not None and workflow.status == HogFlow.State.ARCHIVED:
        raise DocumentInvalid([_workflow_archived(key, compiled.definition.get("status"))])


def _workflow_archived(key: str, file_status: Optional[str]) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.STATUS_CHANGE_NOT_ALLOWED,
        message=f"The workflow with the key {key} is archived, and applying the file would bring it back as {file_status}.",
        why="Someone archived the workflow in PostHog, so a file that still names it does not bring it back on its own.",
        fix=(
            "To apply the file to this workflow, restore it in PostHog first. "
            "To keep it archived, delete the file. "
            "To make a new workflow from the file, give the file a new key."
        ),
        path=("key",),
    )


def _key_conflict(key: str) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.CONFLICT,
        message=f"Another request created or deleted the workflow with the key {key} while this file was applied.",
        why="A key names one workflow in the project, and it changed hands during the apply, so PostHog wrote nothing from this file.",
        fix="Apply the file again. PostHog then updates the workflow with this key.",
        path=("key",),
    )


def _compile(loaded: LoadedContent, team_id: int) -> tuple[CompiledWorkflow, str]:
    try:
        document = validate_document(loaded.data, loaded.scalar_sources)
    except DocumentInvalid as invalid:
        raise DocumentInvalid(loaded.with_validation_errors(invalid.errors))
    if loaded.errors:
        raise DocumentInvalid(loaded.errors)
    compiled = compile_document(document)
    get_template = cache(_get_template)
    errors = template_errors(compiled, get_template) + sender_errors(
        compiled, get_template, partial(_project_email_integration_ids, team_id)
    )
    if errors:
        raise DocumentInvalid(errors)
    return compiled, document.key


def _project_email_integration_ids(team_id: int, integration_ids: set[int]) -> set[int]:
    return set(
        Integration.objects.filter(team_id=team_id, kind="email", id__in=integration_ids).values_list("id", flat=True)
    )


def _get_template(template_id: str) -> Optional[FunctionTemplate]:
    return HogFunctionTemplate.get_template(template_id)


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


def _rejected(invalid: DocumentInvalid, loaded: Optional[LoadedContent]) -> WorkflowCodeRejected:
    located = [_located(error, loaded) for error in invalid.errors]
    located.sort(key=lambda e: (e.line is None, e.line or 0, e.column or 0))
    if len(located) <= MAX_REPORTED_ERRORS:
        return WorkflowCodeRejected(tuple(located))
    return WorkflowCodeRejected((*located[:MAX_REPORTED_ERRORS], _left_out_errors(len(located) - MAX_REPORTED_ERRORS)))


def _left_out_errors(count: int) -> WorkflowCodeError:
    return WorkflowCodeError(
        status=WorkflowCodeErrorStatus.TOO_MANY_ERRORS,
        message=f"The file has {count} more errors than the {MAX_REPORTED_ERRORS} listed here.",
        why=f"PostHog lists the first {MAX_REPORTED_ERRORS} errors in file order, so one response stays readable.",
        fix="Fix the errors listed here, then check the file again to see the rest.",
        path=None,
        line=None,
        column=None,
    )


def _located(error: DocumentError, loaded: Optional[LoadedContent]) -> WorkflowCodeError:
    position = loaded.locate(error) if loaded is not None else None
    return WorkflowCodeError(
        status=error.status,
        message=error.message,
        why=error.why,
        fix=error.fix,
        path=format_path(error.path),
        line=position.line if position else None,
        column=position.column if position else None,
    )
