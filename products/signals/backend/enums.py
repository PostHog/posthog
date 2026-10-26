from enum import StrEnum

from django.utils.functional import Promise

from posthog.enums import LabeledStrEnum

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


class ReportTaskActionKind(LabeledStrEnum):
    # A report action that starts an agent run from the API. See `report_task_actions.py`.
    GET_IT_MERGED = "get_it_merged", "Get it merged"
    MAKE_IT_GREEN = "make_it_green", "Make it green"
    SUGGESTED_PROMPT = "suggested_prompt", "Suggested prompt"


class ReviewerSelectionOutcome(LabeledStrEnum):
    SELECTED = "selected", "Selected"
    NO_SUITABLE_OWNER = "no_suitable_owner", "No suitable owner"
    LOOKUP_FAILED = "lookup_failed", "Lookup failed"


class ReviewerEditAction(LabeledStrEnum):
    ADD = "add", "Add"
    REMOVE = "remove", "Remove"
    REPLACE = "replace", "Replace"
    CONFIRM = "confirm", "Confirm"


class ReportLinkKind(LabeledStrEnum):
    # How one report relates to another, written as a directed `report_link` artefact on the
    # report the sentence starts from: "this report DEPENDS_ON that one". A GitHub issue that
    # specs a stack of dependent pull requests needs the direction recorded, which the older
    # symmetric `related_to` artefact cannot express.
    DEPENDS_ON = "depends_on", "Depends on"
    PART_OF = "part_of", "Part of"
    FOLLOW_UP_OF = "follow_up_of", "Follow-up of"
    DUPLICATE_OF = "duplicate_of", "Duplicate of"
    RECURRENCE_OF = "recurrence_of", "Recurrence of"


class ToolPreset(LabeledStrEnum):
    # Named tool selections a scout config can expand into a saved `allowed_mcp_tools` list.
    # `tool_catalogue.get_scout_tool_catalogue` defines the tools behind each name.
    READ_ONLY = "read_only", "Read only"
    SUPPORT_NOTES = "support_notes", "Support notes"


class SuggestedSourceProduct(LabeledStrEnum):
    # Products a report can suggest the team turn on because the report would have had better
    # evidence with them. Each value must equal a `ProductKey` whose data freshness spec says
    # whether the team already uses the product (see `source_suggestions.py`).
    LOGS = "logs", "Logs"
    SESSION_REPLAY = "session_replay", "Session replay"
    ERROR_TRACKING = "error_tracking", "Error tracking"
    LLM_ANALYTICS = "llm_analytics", "AI observability"


class ReportLinkWritePath(StrEnum):
    # Which surface wrote a `report_link`. `EMIT` writes it with the report, before auto-start reads
    # the link gates. `EDIT` writes it on a report that exists, possibly after auto-start ran.
    # `MERGE` writes the `duplicate_of` link when the merge endpoint folds a report into another.
    EMIT = "emit"
    EDIT = "edit"
    PIPELINE = "pipeline"
    MERGE = "merge"


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
    DATADOG = "datadog"
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
    # Incident management / on-call (record kind: incident)
    PAGERDUTY = "pagerduty"
    OPSGENIE = "opsgenie"
    INCIDENT_IO = "incident_io"
    FIREHYDRANT = "firehydrant"
    SQUADCAST = "squadcast"
    SERVICENOW = "servicenow"
    SOLARWINDS_SERVICE_DESK = "solarwinds_service_desk"
    GRAFANA_IRM = "grafana_irm"
    XMATTERS = "xmatters"
    BETTERSTACK = "betterstack"
    # Error tracking / monitoring
    NEWRELIC = "newrelic"
    TRIGGER_DEV = "trigger_dev"
    CHECKLY = "checkly"
    ROARK = "roark"
    # Data quality / observability
    MONTE_CARLO = "monte_carlo"
    BIGEYE = "bigeye"
    # Cloud security findings
    AWS_SECURITY_HUB = "aws_security_hub"
    AWS_GUARDDUTY = "aws_guardduty"
    AWS_INSPECTOR = "aws_inspector"
    MICROSOFT_DEFENDER_CLOUD_APPS = "microsoft_defender_cloud_apps"
    # Issue trackers / project management
    CLICKUP = "clickup"
    WRIKE = "wrike"
    TRELLO = "trello"
    BUGHERD = "bugherd"
    # Support / CRM cases
    DYNAMICS365 = "dynamics365"
    ZOHO_CRM = "zoho_crm"
    PLANHAT = "planhat"
    # Product feedback / reviews / community
    TRUSTPILOT = "trustpilot"
    OKENDO = "okendo"
    SLEEKPLAN = "sleekplan"
    BETTERMODE = "bettermode"
    DISCOURSE = "discourse"
    MINTLIFY = "mintlify"
    LANGSMITH = "langsmith"
    SPRIG = "sprig"
    GAINSIGHT_PX = "gainsight_px"
    # Tier-2 incidents
    DYNATRACE = "dynatrace"
    STATUSPAGE = "statuspage"
    CRONITOR = "cronitor"
    INSTATUS = "instatus"
    # Tier-2 trackers
    ASANA = "asana"
    MONDAY = "monday"
    PLANE = "plane"
    AZURE_DEVOPS = "azure_devops"
    # Tier-2 support
    HELPSCOUT = "helpscout"
    DECAGON = "decagon"
    VITALLY = "vitally"
    # Tier-2 feedback and surveys
    USERSNAP = "usersnap"
    TYPEFORM = "typeform"
    QUALTRICS = "qualtrics"
    SURVEYMONKEY = "surveymonkey"
    FORMBRICKS = "formbricks"
    SURVICATE = "survicate"
    SURVEYSPARROW = "surveysparrow"
    # Tier-2 security
    LACEWORK = "lacework"
    ORCA_SECURITY = "orca_security"
    TENABLE_VULNERABILITY_MANAGEMENT = "tenable_vulnerability_management"
    # Tier-2 errors and code review
    GOOGLE_PLAY_CONSOLE = "google_play_console"
    AZURE_APPLICATION_INSIGHTS = "azure_application_insights"
    APPSIGNAL = "appsignal"
    CURSOR = "cursor"


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
    INCIDENT = "incident"


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
    SignalSourceProduct.DATADOG: "Datadog",
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
    SignalSourceProduct.PAGERDUTY: "PagerDuty",
    SignalSourceProduct.OPSGENIE: "Opsgenie",
    SignalSourceProduct.INCIDENT_IO: "incident.io",
    SignalSourceProduct.FIREHYDRANT: "FireHydrant",
    SignalSourceProduct.SQUADCAST: "Squadcast",
    SignalSourceProduct.SERVICENOW: "ServiceNow",
    SignalSourceProduct.SOLARWINDS_SERVICE_DESK: "SolarWinds Service Desk",
    SignalSourceProduct.GRAFANA_IRM: "Grafana IRM",
    SignalSourceProduct.XMATTERS: "xMatters",
    SignalSourceProduct.BETTERSTACK: "Better Stack",
    SignalSourceProduct.NEWRELIC: "New Relic",
    SignalSourceProduct.TRIGGER_DEV: "Trigger.dev",
    SignalSourceProduct.CHECKLY: "Checkly",
    SignalSourceProduct.ROARK: "Roark",
    SignalSourceProduct.MONTE_CARLO: "Monte Carlo",
    SignalSourceProduct.BIGEYE: "Bigeye",
    SignalSourceProduct.AWS_SECURITY_HUB: "AWS Security Hub",
    SignalSourceProduct.AWS_GUARDDUTY: "AWS GuardDuty",
    SignalSourceProduct.AWS_INSPECTOR: "AWS Inspector",
    SignalSourceProduct.MICROSOFT_DEFENDER_CLOUD_APPS: "Microsoft Defender for Cloud Apps",
    SignalSourceProduct.CLICKUP: "ClickUp",
    SignalSourceProduct.WRIKE: "Wrike",
    SignalSourceProduct.TRELLO: "Trello",
    SignalSourceProduct.BUGHERD: "BugHerd",
    SignalSourceProduct.DYNAMICS365: "Dynamics 365",
    SignalSourceProduct.ZOHO_CRM: "Zoho CRM",
    SignalSourceProduct.PLANHAT: "Planhat",
    SignalSourceProduct.TRUSTPILOT: "Trustpilot",
    SignalSourceProduct.OKENDO: "Okendo",
    SignalSourceProduct.SLEEKPLAN: "Sleekplan",
    SignalSourceProduct.BETTERMODE: "Bettermode",
    SignalSourceProduct.DISCOURSE: "Discourse",
    SignalSourceProduct.MINTLIFY: "Mintlify",
    SignalSourceProduct.LANGSMITH: "LangSmith",
    SignalSourceProduct.SPRIG: "Sprig",
    SignalSourceProduct.GAINSIGHT_PX: "Gainsight PX",
    SignalSourceProduct.DYNATRACE: "Dynatrace",
    SignalSourceProduct.STATUSPAGE: "Statuspage",
    SignalSourceProduct.CRONITOR: "Cronitor",
    SignalSourceProduct.INSTATUS: "Instatus",
    SignalSourceProduct.ASANA: "Asana",
    SignalSourceProduct.MONDAY: "monday.com",
    SignalSourceProduct.PLANE: "Plane",
    SignalSourceProduct.AZURE_DEVOPS: "Azure DevOps",
    SignalSourceProduct.HELPSCOUT: "Help Scout",
    SignalSourceProduct.DECAGON: "Decagon",
    SignalSourceProduct.VITALLY: "Vitally",
    SignalSourceProduct.USERSNAP: "Usersnap",
    SignalSourceProduct.TYPEFORM: "Typeform",
    SignalSourceProduct.QUALTRICS: "Qualtrics",
    SignalSourceProduct.SURVEYMONKEY: "SurveyMonkey",
    SignalSourceProduct.FORMBRICKS: "Formbricks",
    SignalSourceProduct.SURVICATE: "Survicate",
    SignalSourceProduct.SURVEYSPARROW: "SurveySparrow",
    SignalSourceProduct.LACEWORK: "Lacework",
    SignalSourceProduct.ORCA_SECURITY: "Orca Security",
    SignalSourceProduct.TENABLE_VULNERABILITY_MANAGEMENT: "Tenable Vulnerability Management",
    SignalSourceProduct.GOOGLE_PLAY_CONSOLE: "Google Play Console",
    SignalSourceProduct.AZURE_APPLICATION_INSIGHTS: "Azure Application Insights",
    SignalSourceProduct.APPSIGNAL: "AppSignal",
    SignalSourceProduct.CURSOR: "Cursor",
}


# The Django model's `source_product` choices. Callable so adding a product never lands in migration
# state as a no-op AlterField. Plain `str` values (not enum members) keep the state stable; order
# follows SIGNAL_SOURCE_PRODUCT_LABELS, which matches the original declaration order.
def signal_source_product_choices() -> list[tuple[str, str | Promise]]:
    return [(product.value, label) for product, label in SIGNAL_SOURCE_PRODUCT_LABELS.items()]
