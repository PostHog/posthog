"""Shared constants for the stamphog review workflow stack.

The workflow, its activities, and the client that starts it all read from here so
there is a single source of truth for the task-queue name, activity timeouts, and
the sandbox paths the reviewer-invocation builder and this workflow must agree on.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy

STAMPHOG_TASK_QUEUE = "stamphog-task-queue"

# Where the target repo is cloned inside the review sandbox. The review engine ships into
# ENGINE_DIR, which sits under the checkout, so the engine's repo-root walk finds the checkout and
# reads the injected trusted policy. The context JSON lands at CONTEXT_PATH. These paths stay here
# so that logic.reviewer.build_reviewer_invocation and run_review_in_sandbox agree on them.
STAMPHOG_SANDBOX_REPO_DIR = "/tmp/stamphog/target"
STAMPHOG_SANDBOX_WORKSPACE_DIR = "/tmp/stamphog/workspace"
STAMPHOG_SANDBOX_ENGINE_DIR = f"{STAMPHOG_SANDBOX_REPO_DIR}/tools/pr-approval-agent"

# Reviewer bots whose 👀 reaction means "review in flight" — the hosted workflow waits these out
# server-side before provisioning the sandbox (the sandbox holds no token to poll with). Mirrors the
# engine's TRUSTED_REACTOR_BOTS (products/stamphog/packages/pr-approval-agent/github.py) and its wait timings
# (review_pr.py); the server cannot import the hyphenated engine dir, so keep the two in sync.
STAMPHOG_TRUSTED_REACTOR_BOTS = frozenset(
    {
        "chatgpt-codex-connector[bot]",
        "copilot-pull-request-reviewer[bot]",
        "greptile-apps[bot]",
        "hex-security-app[bot]",
        "veria-ai[bot]",
    }
)
STAMPHOG_BOT_EYES_MAX_AGE_SECONDS = 45 * 60
STAMPHOG_BOT_REVIEW_POLL_SECONDS = 30
STAMPHOG_BOT_REVIEW_MAX_POLLS = 10  # ~300s budget at 30s per poll, matching the engine's wait budget

# The GitHub label Stamphog adds to hand a refused/escalated PR to ReviewHog. ``review-hog.yml``
# routes this label (when applied by stamphog[bot] — the one sanctioned bot exempted from its
# bot-labeler-skip) to the ReviewHog trigger endpoint. Kept here so the activity references the same
# scalar the workflow gates on.
STAMPHOG_REVIEWHOG_LABEL = "reviewhog"
# The posthog-owners resolver package, expected by the engine as a sibling of its own dir
# (gates.py resolves `../owners` for the hogli-resolver ownership format).
STAMPHOG_SANDBOX_OWNERS_DIR = f"{STAMPHOG_SANDBOX_REPO_DIR}/tools/owners"
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

# Optional per-repo files: fetched from the DEFAULT branch and ALWAYS wiped from the PR
# head, but injected only when the default branch has them — there is no server-shipped
# default (an absent steering.md just leaves the reviewer prompt unchanged).
STAMPHOG_STEERING_PATH = ".stamphog/steering.md"
STAMPHOG_OPTIONAL_POLICY_PATHS: tuple[str, ...] = (STAMPHOG_STEERING_PATH,)

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


class SandboxPhaseError(Exception):
    """Marks the review activity's paid phase: the attempt provisioned a sandbox, or found that an
    earlier attempt already did.

    Nothing retries yet, so today this only names the phase in the failure record. It is the marker
    a later retry policy excludes, so a provisioned box and a reviewer agent that ran are never paid
    for twice. See SANDBOX_RETRY_POLICY.
    """


# Still one attempt. The review activity's setup (database reads, the GitHub installation token, the
# minted gateway token) costs nothing and is safe to repeat, so it should retry, and the activity now
# carries what makes that safe: SandboxPhaseError marks the paid phase, and the run records the claim
# that stops a timeout or a lost worker provisioning a second sandbox.
#
# Raising maximum_attempts belongs in a separate change that lands after this one has rolled out.
# Workflow and activity tasks share one unversioned queue, so during a rolling deploy a new workflow
# worker would schedule against an old activity worker, which writes no claim and raises no marker.
# A paid-phase failure there would retry and bill a second review. Once every worker carries the
# marker and the claim, the policy can move.
SANDBOX_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
