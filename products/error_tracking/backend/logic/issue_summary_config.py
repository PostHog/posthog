"""Tunable values for issue summaries.

The model, stack trace limit and cap are placeholders until the offline quality check picks them.
"""

from posthog.token_bucket import Budget

ISSUE_SUMMARY_FLAG = "error-tracking-issue-summaries"
# The issue-created workflow generates the first summary only when this flag and the read flag are both on.
ISSUE_SUMMARY_ON_WRITE_FLAG = "error-tracking-issue-summaries-on-write"

ISSUE_SUMMARY_MODEL = "posthog/zai-org/glm-5.2"
ISSUE_SUMMARY_STACKTRACE_MAX_TOKENS = 2000
ISSUE_SUMMARY_MAX_OUTPUT_TOKENS = 800
ISSUE_SUMMARY_LLM_TIMEOUT_SECONDS = 30.0

# The refill sits well above a busy project's hourly rate of new issues, and the burst absorbs a release that creates
# many issues at once.
ISSUE_SUMMARY_WRITE_BUDGET = Budget(burst=200, per_hour=60)

# Holds one generation per issue at a time. The worker deletes its claim when it finishes, so the TTL only frees an
# issue whose worker died.
ISSUE_SUMMARY_LOCK_TTL_SECONDS = 300
