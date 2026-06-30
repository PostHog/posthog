from enum import StrEnum

# Source-of-truth taxonomy for signals. Django-free (plain StrEnum) so it stays cheap to import
# from contracts.py, the model layer, and the frontend-types codegen alike. StrEnum members compare
# equal to their string value, so they drop into `==` checks and ORM filters unchanged.


class SignalSourceProduct(StrEnum):
    SESSION_REPLAY = "session_replay"
    LLM_ANALYTICS = "llm_analytics"
    GITHUB = "github"
    LINEAR = "linear"
    ZENDESK = "zendesk"
    CONVERSATIONS = "conversations"
    ERROR_TRACKING = "error_tracking"
    ENDPOINTS = "endpoints"
    PGANALYZE = "pganalyze"
    SIGNALS_SCOUT = "signals_scout"
    LOGS = "logs"
    HEALTH_CHECKS = "health_checks"
    REPLAY_VISION = "replay_vision"


class SignalSourceType(StrEnum):
    SESSION_ANALYSIS_CLUSTER = "session_analysis_cluster"
    SESSION_PROBLEM = "session_problem"
    EVALUATION = "evaluation"
    EVALUATION_REPORT = "evaluation_report"
    ISSUE = "issue"
    TICKET = "ticket"
    ISSUE_CREATED = "issue_created"
    ISSUE_REOPENED = "issue_reopened"
    ISSUE_SPIKING = "issue_spiking"
    ENDPOINT_EXECUTION_FAILED = "endpoint_execution_failed"
    ENDPOINT_BREAKDOWN_LIMIT_EXCEEDED = "endpoint_breakdown_limit_exceeded"
    CROSS_SOURCE_ISSUE = "cross_source_issue"
    ALERT_STATE_CHANGE = "alert_state_change"
    HEALTH_ISSUE = "health_issue"
    SCANNER_FINDING = "scanner_finding"


# Human-facing labels for the model's `source_product` choices. Kept beside the enum so a new
# source is a one-file change; values/labels must stay identical to the migration-frozen choices.
SIGNAL_SOURCE_PRODUCT_LABELS: dict[SignalSourceProduct, str] = {
    SignalSourceProduct.SESSION_REPLAY: "Session replay",
    SignalSourceProduct.LLM_ANALYTICS: "LLM analytics",
    SignalSourceProduct.GITHUB: "GitHub",
    SignalSourceProduct.LINEAR: "Linear",
    SignalSourceProduct.ZENDESK: "Zendesk",
    SignalSourceProduct.CONVERSATIONS: "Conversations",
    SignalSourceProduct.ERROR_TRACKING: "Error tracking",
    SignalSourceProduct.PGANALYZE: "pganalyze",
    SignalSourceProduct.SIGNALS_SCOUT: "Signals scout",
    SignalSourceProduct.LOGS: "Logs",
    SignalSourceProduct.HEALTH_CHECKS: "Health checks",
    SignalSourceProduct.ENDPOINTS: "Endpoints",
    SignalSourceProduct.REPLAY_VISION: "Replay Vision",
}

# The Django model's `source_product` choices, frozen-equivalent to the prior nested TextChoices so
# no migration is generated. Plain `str` values (not enum members) keep migration state stable; order
# follows SIGNAL_SOURCE_PRODUCT_LABELS, which matches the original declaration order.
SIGNAL_SOURCE_PRODUCT_CHOICES: list[tuple[str, str]] = [
    (product.value, label) for product, label in SIGNAL_SOURCE_PRODUCT_LABELS.items()
]
