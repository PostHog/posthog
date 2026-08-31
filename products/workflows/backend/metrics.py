"""The metric vocabulary the self-optimising loop reads.

Kept in one place because two readers have to agree: the stub generator that writes a suggestion's
evidence, and the outcome endpoint that reports what the change did. If they name different metrics,
a proposal's "before" and "after" stop being comparable.
"""

# Every hog flow metric is mirrored under this app source with the version appended to the flow id,
# which is what makes a per-version read possible at all. See "Metrics and version attribution" in
# products/workflows/CONTRIBUTING.md.
HOG_FLOW_VERSION_APP_SOURCE = "hog_flow_version"

TARGET_SEND_METRIC = "email_sent"
TARGET_OPEN_METRIC = "email_opened"

# Sends with open/click tracking off. They raise email_sent but can never raise email_opened, so the
# open rate reads against (email_sent - email_untracked); the guardrail rates below apply to every send
# and keep the raw send count. Emitted on the same keys as email_sent at send time, so the subtraction
# is exact — the same contract the metrics summary surface uses (workflowMetricsSummaryLogic trackedSends).
TARGET_UNTRACKED_METRIC = "email_untracked"

# Counter-metrics, read over the same window, step and version as the target. A suggestion that
# lifts opens while raising complaints or bounces is a loss, and these are what make that visible
# before someone approves it.
GUARDRAIL_METRICS = ("email_blocked", "email_bounced")
GUARDRAIL_LABELS = {"email_blocked": "complaint rate", "email_bounced": "bounce rate"}

# Unsubscribes belong in GUARDRAIL_METRICS but nothing emits them: `email_unsubscribed` exists only
# as a name in the worker's metric union (nodejs/src/cdp/types.ts) with no producer. Named here so
# the surfaces can say the number is missing rather than imply a zero.
UNAVAILABLE_GUARDRAILS = ("unsubscribe rate",)

# Below this many observations a rate is noise. Surfaces label it instead of presenting it as a
# finding, and the stub generator won't propose off less than this without --force.
MIN_EVIDENCE_SAMPLE = 20
