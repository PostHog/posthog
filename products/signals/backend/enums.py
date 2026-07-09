from enum import StrEnum

# Source-of-truth taxonomy for signals. Django-free (plain StrEnum) so it stays cheap to import
# from contracts.py, the model layer, and the frontend-types codegen alike. StrEnum members compare
# equal to their string value, so they drop into `==` checks and ORM filters unchanged.


class ReportPriority(StrEnum):
    # P0–P4 importance/urgency scale shared by signal remediations, scout findings, and report
    # priority assessments. One scale, one enum: replaces the codegen-synthesized schema.Priority /
    # schema.Severity that used to leak out of the old TS-first pipeline.
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


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
    ENGINEERING_ANALYTICS = "engineering_analytics"


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
    CI_FLAKY_CHECK = "ci_flaky_check"
    CI_BROKEN_MASTER = "ci_broken_master"
    CI_DURATION_REGRESSION = "ci_duration_regression"


# Plain value lists for ENUM_NAME_OVERRIDES in web.py — drf-spectacular hashes ChoiceField
# choices as (value, value) pairs, which an Enum class path doesn't normalize to.
SIGNAL_SOURCE_PRODUCT_VALUES: list[str] = [product.value for product in SignalSourceProduct]
SIGNAL_SOURCE_TYPE_VALUES: list[str] = [source_type.value for source_type in SignalSourceType]

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
    SignalSourceProduct.ENGINEERING_ANALYTICS: "Engineering analytics",
}

# The Django model's `source_product` choices, frozen-equivalent to the prior nested TextChoices so
# no migration is generated. Plain `str` values (not enum members) keep migration state stable; order
# follows SIGNAL_SOURCE_PRODUCT_LABELS, which matches the original declaration order.
SIGNAL_SOURCE_PRODUCT_CHOICES: list[tuple[str, str]] = [
    (product.value, label) for product, label in SIGNAL_SOURCE_PRODUCT_LABELS.items()
]
