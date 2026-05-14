"""Workflow names, schedule IDs, and Temporal tunables for the referrals research flows."""

from datetime import timedelta

from temporalio.common import RetryPolicy

TWITTER_RESEARCH_WORKFLOW_NAME = "referrals-twitter-research"
INTERNAL_RESEARCH_WORKFLOW_NAME = "referrals-internal-research"

TWITTER_RESEARCH_SCHEDULE_ID = "referrals-twitter-research-schedule"
INTERNAL_RESEARCH_SCHEDULE_ID = "referrals-internal-research-schedule"

# Default look-back. Twitter runs hourly and always scans the previous hour so the
# next firing's window is disjoint from this one (modulo schedule jitter).
TWITTER_DEFAULT_HOURS = 1

# Sandbox runs are capped at MAX_POLL_SECONDS=30min in poll_for_turn. Add a small
# buffer for context resolution + the placeholder side-effect call.
RESEARCH_ACTIVITY_TIMEOUT = timedelta(minutes=35)

# Mirrors the polling cadence in custom_prompt_internals (10s) plus headroom. If the
# activity stops heartbeating for this long, Temporal restarts it.
RESEARCH_HEARTBEAT_TIMEOUT = timedelta(minutes=2)

# Workflow execution timeout — a touch above the activity timeout so a clean failure
# surfaces as a workflow timeout rather than a stuck workflow.
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=40)

# Research activities are expensive (each retry spins up a fresh sandbox + agent).
# Capping at 2 attempts means a transient infra hiccup still recovers without
# burning 4× the time/cost on the rare full-system outage.
RESEARCH_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=30),
    maximum_interval=timedelta(minutes=2),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)
