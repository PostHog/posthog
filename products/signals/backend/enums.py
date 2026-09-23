from enum import StrEnum

from django.utils.functional import Promise

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


class ReportLinkKind(StrEnum):
    # How one report relates to another, written as a directed `report_link` artefact on the
    # report the sentence starts from: "this report DEPENDS_ON that one". A GitHub issue that
    # specs a stack of dependent pull requests needs the direction recorded, which the older
    # symmetric `related_to` artefact cannot express.
    DEPENDS_ON = "depends_on"
    PART_OF = "part_of"
    FOLLOW_UP_OF = "follow_up_of"
    DUPLICATE_OF = "duplicate_of"
    RECURRENCE_OF = "recurrence_of"


REPORT_LINK_KIND_LABELS: dict[ReportLinkKind, str] = {
    ReportLinkKind.DEPENDS_ON: "Depends on",
    ReportLinkKind.PART_OF: "Part of",
    ReportLinkKind.FOLLOW_UP_OF: "Follow-up of",
    ReportLinkKind.DUPLICATE_OF: "Duplicate of",
    ReportLinkKind.RECURRENCE_OF: "Recurrence of",
}


def report_link_kind_choices() -> list[tuple[str, str | Promise]]:
    # drf-spectacular matches an ENUM_NAME_OVERRIDES entry by a hash of the exact (value, label)
    # pairs, so the serializer's ChoiceField and the override must both read this one callable.
    return [(kind.value, label) for kind, label in REPORT_LINK_KIND_LABELS.items()]


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
    # A report check that failed after its report was resolved. Not a source a team connects:
    # the inbox emits it to itself so a fix that stopped holding starts a fresh report.
    SIGNALS_CHECK = "signals_check"
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
    # Search analytics (record kind: search_opportunity)
    GOOGLE_SEARCH_CONSOLE = "google_search_console"


class SignalSourceType(StrEnum):
    SESSION_ANALYSIS_CLUSTER = "session_analysis_cluster"
    SESSION_PROBLEM = "session_problem"
    # No emitter produces EVALUATION any more — AI observability only signals whole eval reports.
    # The value stays in the taxonomy so signals ingested before that still resolve to a label.
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
    SEARCH_OPPORTUNITY = "search_opportunity"
    CHECK_FAILED = "check_failed"


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
    SignalSourceProduct.SIGNALS_CHECK: "Report check",
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
    SignalSourceProduct.GOOGLE_SEARCH_CONSOLE: "Google Search Console",
}


# The Django model's `source_product` choices. Callable so adding a product never lands in migration
# state as a no-op AlterField. Plain `str` values (not enum members) keep the state stable; order
# follows SIGNAL_SOURCE_PRODUCT_LABELS, which matches the original declaration order.
def signal_source_product_choices() -> list[tuple[str, str | Promise]]:
    return [(product.value, label) for product, label in SIGNAL_SOURCE_PRODUCT_LABELS.items()]
