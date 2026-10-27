"""Tunable values for issue summaries.

The model, stack trace limit and cap are placeholders until the offline quality check picks them.
"""

from datetime import timedelta

from posthog.token_bucket import Budget

from products.error_tracking.backend.logic.severity_inference import SEVERITY_INFERENCE_MODEL

ISSUE_SUMMARY_FLAG = "error-tracking-issue-summaries"

ISSUE_SUMMARY_MODEL = "posthog/zai-org/glm-5.2"
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
# Marks a queued task until a worker claims it, so page polls queue at most one task per issue in this window.
# A lost task keeps reads on "generating" for this long, so it stays short.
ISSUE_SUMMARY_QUEUED_TTL_SECONDS = 60
# Bounds the lock calls and the publish when a read queues a task, so a slow Redis cannot hold the request.
ISSUE_SUMMARY_PUBLISH_TIMEOUT_SECONDS = 1.0
# An issue with no recent exception event, or a team out of budget, is not tried again for this long.
# Each try runs the ClickHouse queries before it can find either outcome.
ISSUE_SUMMARY_HOLD_SECONDS = 3600

# The facts cover the same range the issue tool defaults to.
ISSUE_SUMMARY_FACTS_DATE_FROM = "-7d"
ISSUE_SUMMARY_LATEST_EVENT_LOOKBACK_DAYS = 30
# Most issues that someone opens fired recently, so the first lookup reads one day and the full lookback runs on a miss.
ISSUE_SUMMARY_RECENT_EVENT_LOOKBACK_DAYS = 1
