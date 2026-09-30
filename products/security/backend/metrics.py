from prometheus_client import Counter, Gauge

WOULD_BLOCK_COUNTER = Counter(
    "posthog_security_access_would_block_total",
    "Requests an access rule would block, while blocks are logged only",
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
