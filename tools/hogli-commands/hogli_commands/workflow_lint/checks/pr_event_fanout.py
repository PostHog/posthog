"""Cap repo-wide fanout from unscoped pull request event subscriptions.

GitHub counts each directly triggered workflow as a separate run. Small jobs
that listen to every PR should therefore share an existing dispatcher instead
of adding another top-level ``pull_request`` or ``pull_request_target`` trigger.
Path-filtered workflows are excluded because they only dispatch for a subset of
changes.

The per-action ceilings make any increase explicit in code review. Raising one
is allowed when a separate dispatch is justified, but it spends a shared
repo-wide budget and should not happen as a side effect of adding a small job.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import PR_TRIGGERS, Workflow

DEFAULT_PR_ACTIONS = frozenset({"opened", "reopened", "synchronize"})

PR_EVENT_FANOUT_BUDGET: Mapping[str, int] = {
    "closed": 3,
    "converted_to_draft": 1,
    "edited": 3,
    "labeled": 10,
    "opened": 28,
    "ready_for_review": 11,
    "reopened": 24,
    "review_requested": 1,
    "synchronize": 28,
    "unlabeled": 7,
}


def _trigger_configurations(on: object) -> dict[str, object]:
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(str(trigger) for trigger in on)
    if isinstance(on, dict):
        return {str(trigger): config for trigger, config in on.items()}
    return {}


def _configured_actions(config: object) -> frozenset[str]:
    if not isinstance(config, dict):
        return DEFAULT_PR_ACTIONS
    types = config.get("types")
    if isinstance(types, str):
        return frozenset({types})
    if isinstance(types, list):
        actions = frozenset(str(action) for action in types)
        return actions or DEFAULT_PR_ACTIONS
    return DEFAULT_PR_ACTIONS


def _has_paths_filter(config: object) -> bool:
    return isinstance(config, dict) and isinstance(config.get("paths"), list) and bool(config["paths"])


def _unscoped_pr_actions(workflow: Workflow) -> Iterator[str]:
    triggers = _trigger_configurations(workflow.on)
    for event in PR_TRIGGERS:
        if event not in triggers:
            continue
        config = triggers[event]
        if _has_paths_filter(config):
            continue
        yield from _configured_actions(config)


class PrEventFanoutCheck(WorkflowCheck):
    id = "WF008-pr-event-fanout"
    label = "PR event fanout"
    description = "unscoped PR event subscriptions stay within the repo-wide workflow dispatch budget"

    def __init__(self, budget: Mapping[str, int] | None = None) -> None:
        self._budget = dict(PR_EVENT_FANOUT_BUDGET if budget is None else budget)

    @property
    def fix_hint(self) -> str | None:
        return (
            "Avoid adding another always-fire workflow run. Fold small jobs into an existing dispatcher "
            "with the same event and security context, or add a trigger-level `paths:` filter when the whole "
            "workflow is skippable. If another dispatch is necessary, raise the relevant "
            "`PR_EVENT_FANOUT_BUDGET` ceiling so the cost is explicit in review."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        action_counts: Counter[str] = Counter()
        for workflow in workflows:
            action_counts.update(_unscoped_pr_actions(workflow))

        result = CheckResult()
        for action, count in sorted(action_counts.items()):
            budget = self._budget.get(action, 0)
            if count <= budget:
                continue
            result.issues.append(
                Issue(
                    workflow=".github/workflows",
                    message=f"unscoped `{action}` PR dispatch fanout is {count}; budget is {budget}",
                )
            )
        return result


__all__ = ["PR_EVENT_FANOUT_BUDGET", "PrEventFanoutCheck"]
