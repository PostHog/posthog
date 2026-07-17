"""Temporal patch gates shared by the task-run workflow stacks.

Patch IDs are scoped to a single workflow execution's history, so the legacy
``process-task`` workflow and the ``task-management`` orchestrator can share
one gate without colliding.
"""

from temporalio import workflow

# Gates the actionable-state check in the CI follow-up decision: a fingerprint
# change alone no longer wakes the agent — only failing CI or a changes-requested
# review does. Pre-rollout histories dispatched a follow-up on any change, so the
# marker keeps their replays deterministic. Standard two-step Temporal patch
# lifecycle: deprecate_patch once pre-rollout histories drain, then delete.
PATCH_ID_CI_FOLLOW_UP_ACTIONABLE_GATE = "tasks-ci-follow-up-actionable-gate"


def ci_follow_up_actionable_gate() -> bool:
    # True outside a workflow so direct-invocation unit tests exercise the new path.
    if not workflow.in_workflow():
        return True
    return workflow.patched(PATCH_ID_CI_FOLLOW_UP_ACTIONABLE_GATE)
