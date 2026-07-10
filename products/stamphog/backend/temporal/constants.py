"""Shared constants for the stamphog review workflow stack.

The workflow, its activities, and the client that starts it all read from here so
there is a single source of truth for the task-queue name, activity timeouts, and
the sandbox paths the reviewer-invocation builder and this workflow must agree on.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy

STAMPHOG_TASK_QUEUE = "stamphog-task-queue"

# Where the target repo is cloned inside the review sandbox, and where the reviewer
# prompt/instruction files get staged. Kept here so logic.reviewer.build_reviewer_invocation
# and run_review_in_sandbox agree on paths.
STAMPHOG_SANDBOX_REPO_DIR = "/tmp/stamphog/target"
STAMPHOG_SANDBOX_WORKSPACE_DIR = "/tmp/stamphog/workspace"

# Trusted review-norms prose fed to the reviewer as its system guidance. Read from
# the target repo's DEFAULT branch (never PR head) so a PR can't rewrite the norms
# it is judged against.
STAMPHOG_REVIEW_GUIDANCE_PATH = ".stamphog/review-guidance.md"

# Files pulled from the target repo's DEFAULT branch (never PR head) onto the run.
# The policy entrypoint feeds load_policy (folder overrides referenced by it are
# resolved by the policy layer itself); the guidance file feeds the reviewer prompt.
STAMPHOG_POLICY_PATHS: tuple[str, ...] = (".stamphog/policy.yml", STAMPHOG_REVIEW_GUIDANCE_PATH)

# Per-activity start-to-close timeouts.
FETCH_CONTEXT_TIMEOUT = timedelta(minutes=5)
RUN_GATES_TIMEOUT = timedelta(minutes=2)
RUN_REVIEW_TIMEOUT = timedelta(minutes=30)
POST_VERDICT_TIMEOUT = timedelta(minutes=5)
MARK_FAILED_TIMEOUT = timedelta(minutes=1)

# GitHub reads/writes and DB updates are safe to retry; the sticky comment and the
# approval review are both idempotent (upsert / single pending review per head).
ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
)

# The sandbox review provisions a box, clones the repo, and runs the reviewer agent —
# expensive and side-effecting, so a transient failure fails the run rather than
# silently paying for it twice. The workflow-level wrapper marks the run FAILED.
SANDBOX_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
