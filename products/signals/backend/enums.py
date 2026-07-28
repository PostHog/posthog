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
    JIRA = "jira"
    ZENDESK = "zendesk"
    CONVERSATIONS = "conversations"
    ERROR_TRACKING = "error_tracking"
    ENDPOINTS = "endpoints"
    PGANALYZE = "pganalyze"
    SIGNALS_SCOUT = "signals_scout"
    LOGS = "logs"
    HEALTH_CHECKS = "health_checks"
    REPLAY_VISION = "replay_vision"
    ANALYTICS = "analytics"
    # Tier-1 data-warehouse inbox sources (support / issue trackers / error tracking)
    FRESHDESK = "freshdesk"
    FRESHSERVICE = "freshservice"
    FRONT = "front"
    GORGIAS = "gorgias"
    KUSTOMER = "kustomer"
    DIXA = "dixa"
    PLAIN = "plain"
    GITLAB = "gitlab"
    GITEA = "gitea"
    SHORTCUT = "shortcut"
    SENTRY = "sentry"
    ROLLBAR = "rollbar"
    BUGSNAG = "bugsnag"
    HONEYBADGER = "honeybadger"
    RAYGUN = "raygun"
    # Tier-2 security scanners (record kind: scanner_finding)
    SNYK = "snyk"
    SONARQUBE = "sonarqube"
    SEMGREP = "semgrep"
    RAPID7_INSIGHTVM = "rapid7_insightvm"
    # Tier-3 product feedback / feature requests / reviews
    FEATUREBASE = "featurebase"
    FRILL = "frill"
    AHA = "aha"
    USERVOICE = "uservoice"
    PRODUCTBOARD = "productboard"
    CANNY = "canny"
    ASKNICELY = "asknicely"
    RETENTLY = "retently"
    APPFIGURES = "appfigures"
    APPFOLLOW = "appfollow"
    JUDGEME_REVIEWS = "judgeme_reviews"
    # OAuth-connected support sources
    INTERCOM = "intercom"
    HUBSPOT = "hubspot"
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
    ANOMALY_INVESTIGATION = "anomaly_investigation"
    FEEDBACK = "feedback"
    REVIEW = "review"
    CI_FLAKY_CHECK = "ci_flaky_check"
    CI_BROKEN_DEFAULT_BRANCH = "ci_broken_default_branch"
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
    SignalSourceProduct.JIRA: "Jira",
    SignalSourceProduct.ZENDESK: "Zendesk",
    SignalSourceProduct.CONVERSATIONS: "Conversations",
    SignalSourceProduct.ERROR_TRACKING: "Error tracking",
    SignalSourceProduct.PGANALYZE: "pganalyze",
    SignalSourceProduct.SIGNALS_SCOUT: "Signals scout",
    SignalSourceProduct.LOGS: "Logs",
    SignalSourceProduct.HEALTH_CHECKS: "Health checks",
    SignalSourceProduct.ENDPOINTS: "Endpoints",
    SignalSourceProduct.REPLAY_VISION: "Replay Vision",
    SignalSourceProduct.ANALYTICS: "Product analytics",
    SignalSourceProduct.FRESHDESK: "Freshdesk",
    SignalSourceProduct.FRESHSERVICE: "Freshservice",
    SignalSourceProduct.FRONT: "Front",
    SignalSourceProduct.GORGIAS: "Gorgias",
    SignalSourceProduct.KUSTOMER: "Kustomer",
    SignalSourceProduct.DIXA: "Dixa",
    SignalSourceProduct.PLAIN: "Plain",
    SignalSourceProduct.GITLAB: "GitLab",
    SignalSourceProduct.GITEA: "Gitea",
    SignalSourceProduct.SHORTCUT: "Shortcut",
    SignalSourceProduct.SENTRY: "Sentry",
    SignalSourceProduct.ROLLBAR: "Rollbar",
    SignalSourceProduct.BUGSNAG: "Bugsnag",
    SignalSourceProduct.HONEYBADGER: "Honeybadger",
    SignalSourceProduct.RAYGUN: "Raygun",
    SignalSourceProduct.SNYK: "Snyk",
    SignalSourceProduct.SONARQUBE: "SonarQube",
    SignalSourceProduct.SEMGREP: "Semgrep",
    SignalSourceProduct.RAPID7_INSIGHTVM: "Rapid7 InsightVM",
    SignalSourceProduct.FEATUREBASE: "Featurebase",
    SignalSourceProduct.FRILL: "Frill",
    SignalSourceProduct.AHA: "Aha",
    SignalSourceProduct.USERVOICE: "UserVoice",
    SignalSourceProduct.PRODUCTBOARD: "Productboard",
    SignalSourceProduct.CANNY: "Canny",
    SignalSourceProduct.ASKNICELY: "AskNicely",
    SignalSourceProduct.RETENTLY: "Retently",
    SignalSourceProduct.APPFIGURES: "Appfigures",
    SignalSourceProduct.APPFOLLOW: "AppFollow",
    SignalSourceProduct.JUDGEME_REVIEWS: "Judge.me",
    SignalSourceProduct.INTERCOM: "Intercom",
    SignalSourceProduct.HUBSPOT: "HubSpot",
    SignalSourceProduct.ENGINEERING_ANALYTICS: "Engineering analytics",
}

# The Django model's `source_product` choices, frozen-equivalent to the prior nested TextChoices so
# no migration is generated. Plain `str` values (not enum members) keep migration state stable; order
# follows SIGNAL_SOURCE_PRODUCT_LABELS, which matches the original declaration order.
SIGNAL_SOURCE_PRODUCT_CHOICES: list[tuple[str, str]] = [
    (product.value, label) for product, label in SIGNAL_SOURCE_PRODUCT_LABELS.items()
]
