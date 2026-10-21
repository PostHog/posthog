"""Tunable values for issue summaries.

The model, stack trace limit and cap are placeholders until the offline quality check picks them.
"""

from datetime import timedelta

from posthog.token_bucket import Budget

from products.error_tracking.backend.logic.severity_inference import SEVERITY_INFERENCE_MODEL

ISSUE_SUMMARY_FLAG = "error-tracking-issue-summaries"

ISSUE_SUMMARY_MODEL = "gpt-4.1-mini"
ISSUE_SUMMARY_CATEGORY_MODEL = SEVERITY_INFERENCE_MODEL
ISSUE_SUMMARY_STACKTRACE_MAX_TOKENS = 2000
ISSUE_SUMMARY_MAX_OUTPUT_TOKENS = 800
ISSUE_SUMMARY_LLM_TIMEOUT_SECONDS = 30.0

# A team gets 100 summaries at once, then about 120 a day.
ISSUE_SUMMARY_BUDGET = Budget(burst=100, per_hour=5)

# A changed input hash regenerates a summary at most this often.
ISSUE_SUMMARY_MIN_REGENERATE_INTERVAL = timedelta(hours=24)

# Holds one generation per issue at a time. It is never released, so it also spaces out retries after a failure.
ISSUE_SUMMARY_LOCK_TTL_SECONDS = 300

# The facts cover the same range the issue tool defaults to.
ISSUE_SUMMARY_FACTS_DATE_FROM = "-7d"
ISSUE_SUMMARY_LATEST_EVENT_LOOKBACK_DAYS = 30
