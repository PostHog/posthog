import json
from dataclasses import replace
from typing import Any

from django.db import models

from posthog.dataclasses import frozen

from products.workflows.backend.services.workflow_code.compiler import EXIT_NODE_ID, TRIGGER_NODE_ID


class WorkflowCodePlanResult(models.TextChoices):
    CREATE = "create"
    UPDATE = "update"
    STAGE = "stage"
    UNCHANGED = "unchanged"


class WorkflowCodeApplyResult(models.TextChoices):
    CREATED = "created"
    UPDATED = "updated"
    STAGED = "staged"
    UNCHANGED = "unchanged"


_METADATA_FIELDS = ("name", "description")
_CONTENT_FIELDS = ("exit_condition", "variables", "edges")
_MAX_CHANGE_DEPTH = 2


@frozen
class WorkflowState:
    """A workflow's name, description and status, with its content normalized for comparison."""

    name: str
    description: str
    status: str
    content: dict[str, Any]


@frozen
class WorkflowSummary:
    id: str
    key: str
    name: str | None
    version: int
    status: str


@frozen
class StepSummary:
    id: str
    name: str
    type: str


@frozen
class ChangedStep:
    id: str
    name: str
    type: str
    changes: list[str]


@frozen
class PlanWarning:
    message: str
    fix: str
    path: str | None = None


@frozen
class CodePlan:
    result: WorkflowCodePlanResult
    workflow: WorkflowSummary | None
    changed_fields: list[str]
    status: dict[str, str | None]
    added_steps: list[StepSummary]
    changed_steps: list[ChangedStep]
    removed_steps: list[dict[str, Any]]
    in_flight_runs: int | None
    position_unknown: int | None
    empty_variables: list[dict[str, Any]]
    schedule_conflicts: list[dict[str, Any]]
    discards_draft: bool


def plan_create(proposed: WorkflowState) -> CodePlan:
    return CodePlan(
        result=WorkflowCodePlanResult.CREATE,
        workflow=None,
        changed_fields=[],
        status={"from": None, "to": proposed.status},
        added_steps=[_step_summary(action) for action in _steps(proposed)],
        changed_steps=[],
        removed_steps=[],
        in_flight_runs=0,
        position_unknown=0,
        empty_variables=[],
        schedule_conflicts=[],
        discards_draft=False,
    )


def plan_update(
    *,
    workflow: WorkflowSummary,
    stored: WorkflowState,
    proposed: WorkflowState,
    impact: dict[str, Any],
    in_flight_runs: int | None,
    has_draft: bool,
) -> CodePlan:
    """Compare the stored workflow with the file. `impact` is what build_publish_impact returns for the pair."""
    stored_steps = {action["id"]: action for action in _steps(stored)}
    proposed_steps = _steps(proposed)
    canonical_stored, canonical_proposed = _canonical(stored), _canonical(proposed)
    unchanged = canonical_stored == canonical_proposed
    return CodePlan(
        result=WorkflowCodePlanResult.UNCHANGED if unchanged else WorkflowCodePlanResult.UPDATE,
        workflow=workflow,
        changed_fields=_changed_fields(canonical_stored, canonical_proposed),
        status={"from": stored.status, "to": proposed.status},
        added_steps=[_step_summary(action) for action in proposed_steps if action["id"] not in stored_steps],
        changed_steps=[
            ChangedStep(id=action["id"], name=_step_name(action), type=action.get("type") or "", changes=changes)
            for action in proposed_steps
            if action["id"] in stored_steps and (changes := _changed_paths(stored_steps[action["id"]], action))
        ],
        removed_steps=impact["deleted_steps"],
        in_flight_runs=in_flight_runs,
        position_unknown=impact["position_unknown"],
        empty_variables=impact["empty_variables"],
        schedule_conflicts=impact["schedule_conflicts"],
        discards_draft=has_draft and not unchanged,
    )


def plan_stage(plan: CodePlan, staged: WorkflowState, proposed: WorkflowState) -> CodePlan:
    """The plan for content staged as a draft over `staged`, the draft or the live content it replaces."""
    unchanged = _canonical(staged) == _canonical(proposed)
    return replace(
        plan,
        result=WorkflowCodePlanResult.UNCHANGED if unchanged else WorkflowCodePlanResult.STAGE,
        discards_draft=False,
    )


def plan_warnings(plan: CodePlan) -> list[PlanWarning]:
    return [_removed_step_warning(step) for step in plan.removed_steps if step["runs"] is None or step["runs"] > 0]


def _removed_step_warning(step: dict[str, Any]) -> PlanWarning:
    moves_to = step["moves_to"]
    where = f"They move to {moves_to['name']}." if moves_to else "They leave the workflow."
    if step["runs"] is None:
        message = f"This file removes {step['name']}, and PostHog could not count the people in it. {where}"
    else:
        people = "1 person is" if step["runs"] == 1 else f"{step['runs']} people are"
        message = f"{people} in {step['name']}, which this file removes. {where}"
    return PlanWarning(
        message=message,
        fix=f"If you renamed the step, add id: {step['action_id']} to it to keep them where they are.",
    )


def _canonical(state: WorkflowState) -> WorkflowState:
    """The state with the parts that carry no meaning made equal: the order of actions and edges, no variables,
    and a step field set to null, as the workflow editor sends unset fields."""
    actions = [
        {field: value for field, value in action.items() if value is not None}
        for action in state.content.get("actions") or []
    ]
    content = {
        **state.content,
        "actions": sorted(actions, key=lambda action: str(action.get("id"))),
        "edges": sorted(
            state.content.get("edges") or [], key=lambda edge: json.dumps(edge, sort_keys=True, default=str)
        ),
        "variables": state.content.get("variables") or [],
    }
    return replace(state, content=content)


def _steps(state: WorkflowState) -> list[dict[str, Any]]:
    return [
        action
        for action in state.content.get("actions") or []
        if action.get("id") not in (TRIGGER_NODE_ID, EXIT_NODE_ID)
    ]


def _step_summary(action: dict[str, Any]) -> StepSummary:
    return StepSummary(id=action["id"], name=_step_name(action), type=action.get("type") or "")


def _step_name(action: dict[str, Any]) -> str:
    return action.get("name") or action["id"]


def _changed_fields(stored: WorkflowState, proposed: WorkflowState) -> list[str]:
    changed = [field for field in _METADATA_FIELDS if getattr(stored, field) != getattr(proposed, field)]
    changed += [field for field in _CONTENT_FIELDS if stored.content.get(field) != proposed.content.get(field)]
    for field, action_id in (("trigger", TRIGGER_NODE_ID), ("exit", EXIT_NODE_ID)):
        if _action(stored, action_id) != _action(proposed, action_id):
            changed.append(field)
    return changed


def _action(state: WorkflowState, action_id: str) -> dict[str, Any] | None:
    return next((a for a in state.content.get("actions") or [] if a.get("id") == action_id), None)


def _changed_paths(old: Any, new: Any, prefix: str = "", depth: int = 1) -> list[str]:
    if old == new:
        return []
    if depth > _MAX_CHANGE_DEPTH or not isinstance(old, dict) or not isinstance(new, dict):
        return [prefix]
    paths: list[str] = []
    for key in sorted(old.keys() | new.keys()):
        paths += _changed_paths(old.get(key), new.get(key), f"{prefix}.{key}" if prefix else key, depth + 1)
    return paths
