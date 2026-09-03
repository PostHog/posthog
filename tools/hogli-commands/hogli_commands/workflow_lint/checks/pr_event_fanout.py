"""Cap repo-wide fanout from unscoped pull request event subscriptions.

GitHub counts each directly triggered workflow as a separate run. Small jobs
that listen to every PR should therefore share an existing dispatcher instead
of adding another top-level ``pull_request`` or ``pull_request_target`` trigger.
A trigger-level ``paths:`` allowlist is excluded, because it only dispatches for
a subset of changes. ``paths-ignore`` still counts: it usually excludes a narrow
slice, so the workflow fires on nearly every PR anyway.

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

# Labels arrive one PR at a time, so they cannot produce the simultaneous burst this
# budget guards, and every label subscriber left in the tree wants the trigger. Merge
# gates are a separate rule that a repo-wide sum cannot express; AGENTS.md owns it.
UNBUDGETED_ACTIONS = frozenset({"labeled", "unlabeled"})

PR_EVENT_FANOUT_BUDGET: Mapping[str, int] = {
    "closed": 3,
    "converted_to_draft": 1,
    # pr-approval-agent listens for base retargets (`edited` with `changes.base`); title/body
    # edits skip every job there, but GitHub still counts the dispatch.
    "edited": 4,
    "opened": 28,
    "ready_for_review": 11,
    "reopened": 24,
    "review_requested": 1,
    "synchronize": 28,
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
    types = config.get("types") if isinstance(config, dict) else None
    if isinstance(types, str):
        return frozenset({types})
    if isinstance(types, list):
        # An empty list selects no activity type, so the workflow never dispatches.
        return frozenset(str(action) for action in types)
    return DEFAULT_PR_ACTIONS


def _has_paths_filter(config: object) -> bool:
    return isinstance(config, dict) and isinstance(config.get("paths"), list) and bool(config["paths"])


def _unscoped_pr_actions(workflow: Workflow) -> Iterator[str]:
    for event, config in _trigger_configurations(workflow.on).items():
        if event not in PR_TRIGGERS:
            continue
        if _has_paths_filter(config):
            continue
        yield from _configured_actions(config) - UNBUDGETED_ACTIONS


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
