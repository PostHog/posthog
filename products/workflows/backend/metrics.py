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
# Both rates count what the window recorded, not what a cohort went on to do.
# Clicks read against the same denominator as opens; the two move for different reasons.
TARGET_CLICK_METRIC = "email_link_clicked"

# Sends with tracking off can never record an open, so the open rate reads against
# (email_sent - email_untracked); guardrail rates keep the raw send count.
TARGET_UNTRACKED_METRIC = "email_untracked"

# Counter-metrics read over the same window, step and version as the target.
GUARDRAIL_METRICS = ("email_blocked", "email_bounced")
GUARDRAIL_LABELS = {"email_blocked": "complaint rate", "email_bounced": "bounce rate"}

# `email_unsubscribed` exists only as a name in the worker's metric union with no producer. Named so
# the surfaces can say the number is missing rather than imply a zero.
UNAVAILABLE_GUARDRAILS = ("unsubscribe rate",)

# Below this many observations a rate is noise.
MIN_EVIDENCE_SAMPLE = 20
