import json
from typing import Any

import pytest

from products.signals.backend.contracts import SIGNAL_VARIANT_LOOKUP
from products.signals.backend.emission.registry import get_signal_config, is_signal_emission_registered
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

# (source_type, warehouse table, source_product, record kind) for each Tier-1 source added in this batch.
TIER1_SOURCES = [
    (ExternalDataSourceType.FRESHDESK, "tickets", "freshdesk", "ticket"),
    (ExternalDataSourceType.FRESHSERVICE, "tickets", "freshservice", "ticket"),
    (ExternalDataSourceType.FRONT, "conversations", "front", "ticket"),
    (ExternalDataSourceType.GORGIAS, "tickets", "gorgias", "ticket"),
    (ExternalDataSourceType.KUSTOMER, "conversations", "kustomer", "ticket"),
    (ExternalDataSourceType.DIXA, "conversations", "dixa", "ticket"),
    (ExternalDataSourceType.PLAIN, "threads", "plain", "ticket"),
    (ExternalDataSourceType.GITLAB, "issues", "gitlab", "issue"),
    (ExternalDataSourceType.GITEA, "issues", "gitea", "issue"),
    (ExternalDataSourceType.SHORTCUT, "stories", "shortcut", "issue"),
    (ExternalDataSourceType.SENTRY, "issues", "sentry", "issue"),
    (ExternalDataSourceType.ROLLBAR, "items", "rollbar", "issue"),
    (ExternalDataSourceType.BUGSNAG, "errors", "bugsnag", "issue"),
    (ExternalDataSourceType.HONEYBADGER, "faults", "honeybadger", "issue"),
    (ExternalDataSourceType.RAYGUN, "error_groups", "raygun", "issue"),
    (ExternalDataSourceType.DATADOG, "error_tracking_issues", "datadog", "issue"),
    (ExternalDataSourceType.DATADOG, "error_spans", "datadog", "issue"),
    (ExternalDataSourceType.DATADOG, "error_logs", "datadog", "issue"),
    (ExternalDataSourceType.DATADOG, "incidents", "datadog", "issue"),
    (ExternalDataSourceType.DATADOG, "monitor_alerts", "datadog", "issue"),
    # Tier-2 security scanners
    (ExternalDataSourceType.SNYK, "issues", "snyk", "scanner_finding"),
    (ExternalDataSourceType.SONARQUBE, "issues", "sonarqube", "scanner_finding"),
    (ExternalDataSourceType.SEMGREP, "sast_findings", "semgrep", "scanner_finding"),
    (ExternalDataSourceType.RAPID7INSIGHTVM, "vulnerabilities", "rapid7_insightvm", "scanner_finding"),
    # Tier-3 product feedback / feature requests
    (ExternalDataSourceType.FEATUREBASE, "posts", "featurebase", "feedback"),
    (ExternalDataSourceType.FRILL, "ideas", "frill", "feedback"),
    (ExternalDataSourceType.AHA, "ideas", "aha", "feedback"),
    (ExternalDataSourceType.USERVOICE, "suggestions", "uservoice", "feedback"),
    (ExternalDataSourceType.PRODUCTBOARD, "notes", "productboard", "feedback"),
    (ExternalDataSourceType.CANNY, "posts", "canny", "feedback"),
    (ExternalDataSourceType.ASKNICELY, "responses", "asknicely", "feedback"),
    (ExternalDataSourceType.RETENTLY, "feedback", "retently", "feedback"),
    # Tier-2 survey tools (answers in a JSON column)
    (ExternalDataSourceType.USERSNAP, "feedbacks", "usersnap", "feedback"),
    (ExternalDataSourceType.TYPEFORM, "responses", "typeform", "feedback"),
    (ExternalDataSourceType.QUALTRICS, "survey_responses", "qualtrics", "feedback"),
    (ExternalDataSourceType.SURVEYMONKEY, "survey_responses", "surveymonkey", "feedback"),
    (ExternalDataSourceType.FORMBRICKS, "responses", "formbricks", "feedback"),
    (ExternalDataSourceType.SURVICATE, "responses", "survicate", "feedback"),
    (ExternalDataSourceType.SURVEYSPARROW, "responses", "surveysparrow", "feedback"),
    # Tier-3 reviews
    (ExternalDataSourceType.APPFIGURES, "reviews", "appfigures", "review"),
    (ExternalDataSourceType.APPFOLLOW, "reviews", "appfollow", "review"),
    (ExternalDataSourceType.JUDGEMEREVIEWS, "reviews", "judgeme_reviews", "review"),
    # OAuth-connected support sources
    (ExternalDataSourceType.INTERCOM, "conversations", "intercom", "ticket"),
    (ExternalDataSourceType.HUBSPOT, "tickets", "hubspot", "ticket"),
    # CRM case tools
    (ExternalDataSourceType.DYNAMICS365, "Cases", "dynamics365", "ticket"),
    (ExternalDataSourceType.ZOHOCRM, "Cases", "zoho_crm", "ticket"),
    # Incident management / on-call
    (ExternalDataSourceType.PAGERDUTY, "incidents", "pagerduty", "incident"),
    (ExternalDataSourceType.OPSGENIE, "alerts", "opsgenie", "incident"),
    (ExternalDataSourceType.INCIDENTIO, "incidents", "incident_io", "incident"),
    (ExternalDataSourceType.FIREHYDRANT, "incidents", "firehydrant", "incident"),
    (ExternalDataSourceType.SQUADCAST, "incidents", "squadcast", "incident"),
    (ExternalDataSourceType.SERVICENOW, "incidents", "servicenow", "incident"),
    (ExternalDataSourceType.SOLARWINDSSERVICEDESK, "incidents", "solarwinds_service_desk", "incident"),
    (ExternalDataSourceType.GRAFANAIRM, "incidents", "grafana_irm", "incident"),
    (ExternalDataSourceType.XMATTERS, "incidents", "xmatters", "incident"),
    (ExternalDataSourceType.BETTERSTACK, "incidents", "betterstack", "incident"),
    (ExternalDataSourceType.DYNATRACE, "problems", "dynatrace", "incident"),
    (ExternalDataSourceType.STATUSPAGE, "incidents", "statuspage", "incident"),
    (ExternalDataSourceType.CRONITOR, "issues", "cronitor", "incident"),
    (ExternalDataSourceType.INSTATUS, "incidents", "instatus", "incident"),
    # Work trackers
    (ExternalDataSourceType.ASANA, "tasks", "asana", "issue"),
    (ExternalDataSourceType.MONDAY, "items", "monday", "issue"),
    (ExternalDataSourceType.PLANE, "work_items", "plane", "issue"),
    (ExternalDataSourceType.AZUREDEVOPS, "work_item_revisions", "azure_devops", "issue"),
    # Data quality / observability
    (ExternalDataSourceType.MONTECARLO, "alerts", "monte_carlo", "incident"),
    (ExternalDataSourceType.BIGEYE, "Issues", "bigeye", "incident"),
    # Support
    (ExternalDataSourceType.HELPSCOUT, "conversations", "helpscout", "ticket"),
    (ExternalDataSourceType.DECAGON, "conversations", "decagon", "ticket"),
    (ExternalDataSourceType.VITALLY, "Conversations", "vitally", "ticket"),
    # Tier-2 security tools
    (ExternalDataSourceType.LACEWORK, "alerts", "lacework", "scanner_finding"),
    (ExternalDataSourceType.ORCASECURITY, "alerts", "orca_security", "scanner_finding"),
    (
        ExternalDataSourceType.TENABLEVULNERABILITYMANAGEMENT,
        "vulnerabilities",
        "tenable_vulnerability_management",
        "scanner_finding",
    ),
    # Error monitors
    (ExternalDataSourceType.TRIGGERDEV, "errors", "trigger_dev", "issue"),
    (ExternalDataSourceType.CHECKLY, "error_groups", "checkly", "issue"),
    (ExternalDataSourceType.ROARK, "issue", "roark", "issue"),
    # Community, survey and docs feedback
    (ExternalDataSourceType.SLEEKPLAN, "Posts", "sleekplan", "feedback"),
    (ExternalDataSourceType.BETTERMODE, "posts", "bettermode", "feedback"),
    (ExternalDataSourceType.DISCOURSE, "posts", "discourse", "feedback"),
    (ExternalDataSourceType.MINTLIFY, "feedback", "mintlify", "feedback"),
    (ExternalDataSourceType.LANGSMITH, "feedback", "langsmith", "feedback"),
    (ExternalDataSourceType.SPRIG, "Responses", "sprig", "feedback"),
    (ExternalDataSourceType.GAINSIGHTPX, "survey_responses", "gainsight_px", "feedback"),
    # Business and product reviews
    (ExternalDataSourceType.TRUSTPILOT, "service_reviews", "trustpilot", "review"),
    (ExternalDataSourceType.OKENDO, "reviews", "okendo", "review"),
    # Cloud security
    (ExternalDataSourceType.AWSSECURITYHUB, "findings", "aws_security_hub", "scanner_finding"),
    (ExternalDataSourceType.AWSGUARDDUTY, "findings", "aws_guardduty", "scanner_finding"),
    (ExternalDataSourceType.AWSINSPECTOR, "findings", "aws_inspector", "scanner_finding"),
    (ExternalDataSourceType.MICROSOFTDEFENDERCLOUDAPPS, "alerts", "microsoft_defender_cloud_apps", "scanner_finding"),
    # Tier-2 errors and code review
    (ExternalDataSourceType.GOOGLEPLAYCONSOLE, "error_issues", "google_play_console", "issue"),
    (ExternalDataSourceType.AZUREAPPLICATIONINSIGHTS, "exceptions", "azure_application_insights", "issue"),
    (ExternalDataSourceType.APPSIGNAL, "exception_incidents", "appsignal", "issue"),
    (ExternalDataSourceType.CURSOR, "bugbot_reviews", "cursor", "issue"),
]

IDS = [product for _, _, product, _ in TIER1_SOURCES]


_LONG_TEXT = "The export button crashes whenever a board has more than fifty cards"

# Survey tools keep their answers in a JSON column, so a full record needs real answer JSON.
_SURVEY_ANSWERS = {
    "usersnap": ("ordered_inputs", json.dumps([{"label": "Comment", "text_value": _LONG_TEXT}])),
    "typeform": ("answers", json.dumps([{"type": "text", "text": _LONG_TEXT, "field": {"type": "long_text"}}])),
    "qualtrics": ("values", json.dumps({"QID1": "2", "QID2_TEXT": _LONG_TEXT})),
    "surveymonkey": ("pages", json.dumps([{"questions": [{"answers": [{"text": _LONG_TEXT}]}]}])),
    "formbricks": ("data", json.dumps({"q1": "yes", "q2": _LONG_TEXT})),
    "survicate": ("answers", json.dumps([{"type": "text", "answer": _LONG_TEXT}])),
    "surveysparrow": ("answers", json.dumps([{"question_type": "TextInput", "answer": _LONG_TEXT}])),
}


def _mock_record(fields: tuple[str, ...], product: str = "") -> dict:
    """A full record covering every SELECTed column, with plausible types."""
    record: dict = {}
    for field in fields:
        name = field.rsplit(" AS ", 1)[-1]
        if product in _SURVEY_ANSWERS and name == _SURVEY_ANSWERS[product][0]:
            record[name] = _SURVEY_ANSWERS[product][1]
        elif name in ("tags", "labels", "projects"):
            record[name] = '[{"name": "one"}, {"name": "two"}]' if name == "projects" else '["one", "two"]'
        elif name == "column_values":
            record[name] = '[{"id": "a", "type": "text", "text": "some text"}]'
        elif name == "messages":
            record[name] = '[{"role": "USER", "text": "hello", "body": "hello"}]'
        elif name == "bugs_found":
            record[name] = 2
        elif name == "dry_run":
            record[name] = False
        elif name == "bugs":
            record[name] = '[{"severity": "high", "resolution_status": "unresolved"}]'
        elif name in ("id", "iid", "project_id", "number", "workflow_state_id"):
            record[name] = 123
        else:
            record[name] = f"value-{name}"
    return record


@pytest.mark.parametrize("source_type,table,product,kind", TIER1_SOURCES, ids=IDS)
def test_source_is_registered(source_type, table, product, kind):
    assert is_signal_emission_registered(source_type.value, table)
    config = get_signal_config(source_type.value, table)
    assert config is not None
    assert config.source_product == product
    assert config.source_type == kind


@pytest.mark.parametrize("source_type,table,product,kind", TIER1_SOURCES, ids=IDS)
def test_emitter_output_matches_contract(source_type, table, product, kind):
    config = get_signal_config(source_type.value, table)
    assert config is not None
    output = config.emitter(1, _mock_record(config.fields, product))
    assert output is not None, f"{product} emitter returned None for a full record"
    assert output.source_product == product
    assert output.source_type == kind

    variant = SIGNAL_VARIANT_LOOKUP.get((output.source_product, output.source_type))
    assert variant is not None, f"no contract variant for ({output.source_product}, {output.source_type})"
    # extra="forbid" + strict types: this fails if the emitted extra drifts from the contract.
    # Splat via a dict[str, Any] because `variant` is typed as the base class, which doesn't
    # declare the discriminator/extra fields the concrete variant adds.
    variant_fields: dict[str, Any] = {
        "source_id": output.source_id,
        "description": output.description,
        "weight": output.weight,
        "extra": output.extra,
        "source_type": output.source_type,
        "source_product": output.source_product,
    }
    variant(**variant_fields)


@pytest.mark.parametrize("source_type,table,product,kind", TIER1_SOURCES, ids=IDS)
def test_config_has_actionability_and_summarization_prompts(source_type, table, product, kind):
    config = get_signal_config(source_type.value, table)
    assert config is not None
    assert config.actionability_prompt is not None and "{description}" in config.actionability_prompt
    assert config.summarization_prompt is not None and "{description}" in config.summarization_prompt
