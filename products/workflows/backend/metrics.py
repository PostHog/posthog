"""The metric vocabulary the self-optimising loop reads.

Kept in one place because the two sides of a suggestion have to agree: whatever writes the evidence
- a Scout, over the API - and the outcome endpoint that reports what the change did. If they name
different metrics, a proposal's "before" and "after" stop being comparable.
"""

# Every hog flow metric is mirrored under this app source with the version appended to the flow id,
# which is what makes a per-version read possible at all. See "Metrics and version attribution" in
# products/workflows/CONTRIBUTING.md.
HOG_FLOW_VERSION_APP_SOURCE = "hog_flow_version"

TARGET_SEND_METRIC = "email_sent"
TARGET_OPEN_METRIC = "email_opened"
# Both rates count what was recorded inside the window, not what a cohort of sends went on to do: an
# open logged today can belong to a send from before the window opened. Over a window much longer
# than the time people take to open an email the effect is small, and both sides of an outcome carry
# it equally, but a narrow window will read a rate that no cohort of sends actually produced.
#
# Clicks, read against the same denominator as opens. A subject line gets a message opened; the body
# and its call to action are what get it clicked, so the two rates move for different reasons and a
# suggestion that lifts one while flattening the other is worth seeing.
TARGET_CLICK_METRIC = "email_link_clicked"

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

# Below this many observations a rate is noise. Surfaces label it rather than presenting it as a
# finding, and a producer has no business proposing off less than this.
MIN_EVIDENCE_SAMPLE = 20
