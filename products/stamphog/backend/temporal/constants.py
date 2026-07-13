"""Shared constants for the stamphog review workflow stack.

The workflow, its activities, and the client that starts it all read from here so
there is a single source of truth for the task-queue name, activity timeouts, and
the sandbox paths the reviewer-invocation builder and this workflow must agree on.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy

STAMPHOG_TASK_QUEUE = "stamphog-task-queue"

# Where the target repo is cloned inside the review sandbox. The Action's review
# engine is shipped into ENGINE_DIR (under the checkout, so its repo-root walk finds
# the checkout and reads the injected trusted policy); the context JSON lands at
# CONTEXT_PATH. Kept here so logic.reviewer.build_reviewer_invocation and
# run_review_in_sandbox agree on paths.
STAMPHOG_SANDBOX_REPO_DIR = "/tmp/stamphog/target"
STAMPHOG_SANDBOX_WORKSPACE_DIR = "/tmp/stamphog/workspace"
STAMPHOG_SANDBOX_ENGINE_DIR = f"{STAMPHOG_SANDBOX_REPO_DIR}/tools/pr-approval-agent"
STAMPHOG_SANDBOX_CONTEXT_PATH = f"{STAMPHOG_SANDBOX_REPO_DIR}/.stamphog_review_context.json"

# Trusted review-norms prose the engine reads as its reviewer system guidance, and
# the gate policy entrypoint. Both are fetched from the target repo's DEFAULT branch
# (never PR head) and written over the checkout's copies before the engine runs, so
# a PR can't rewrite the policy or norms it is judged against.
STAMPHOG_REVIEW_GUIDANCE_PATH = ".stamphog/review-guidance.md"
STAMPHOG_POLICY_ENTRYPOINT = ".stamphog/policy.yml"

# Files pulled from the target repo's DEFAULT branch onto the run and injected into
# the sandbox checkout (overwriting any PR-head copy) as the trusted policy surface.
STAMPHOG_POLICY_PATHS: tuple[str, ...] = (STAMPHOG_POLICY_ENTRYPOINT, STAMPHOG_REVIEW_GUIDANCE_PATH)

# Per-activity start-to-close timeouts.
FETCH_CONTEXT_TIMEOUT = timedelta(minutes=5)
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
