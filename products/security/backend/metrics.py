from prometheus_client import Counter, Gauge

WOULD_BLOCK_COUNTER = Counter(
    "posthog_security_access_would_block_total",
    "Requests an access rule would block, while blocks are logged only",
    labelnames=["surface", "call_site", "target_type"],
)
# Counts every completed decision, whatever its outcome. WOULD_BLOCK_COUNTER only moves on a
# block, so an empty would-block series cannot tell "the check ran and nothing matched" from
# "the check never ran". This counter is the denominator that tells them apart.
DECISIONS_COUNTER = Counter(
    "posthog_security_access_decisions_total",
    "Access decisions evaluated, by surface, call site and outcome",
    labelnames=["surface", "call_site", "outcome"],
)
REFUSALS_COUNTER = Counter(
    "posthog_security_access_refusals_total",
    "Requests an access rule refused, on a surface that enforces blocks",
    labelnames=["surface", "call_site", "target_type"],
)
DECISION_ERRORS_COUNTER = Counter(
    "posthog_security_access_decision_errors_total",
    "Access decisions that raised and were treated as allow",
    labelnames=["call_site"],
)
SKIPPED_RULES_COUNTER = Counter(
    "posthog_security_access_rules_skipped_total",
    "Snapshot rules this release could not read",
)
SYNC_COUNTER = Counter(
    "posthog_security_access_rules_sync_total",
    "Snapshot pulls from the security hub, by result",
    labelnames=["result"],  # updated | unchanged | not_configured | failed | stale
)
LAST_SYNC_GAUGE = Gauge(
    "posthog_security_access_rules_last_sync_timestamp_seconds",
    "Unix time of the last successful snapshot pull; alert when it falls behind",
)
RULES_GAUGE = Gauge(
    "posthog_security_access_rules_count",
    "Readable rules in the last stored snapshot",
)
HUB_API_AUTH_COUNTER = Counter(
    "posthog_security_hub_api_calls_total",
    "Authenticated calls from the security hub, by operation",
    labelnames=["op"],
)
