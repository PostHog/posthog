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
    # Tier-3 reviews
    (ExternalDataSourceType.APPFIGURES, "reviews", "appfigures", "review"),
    (ExternalDataSourceType.APPFOLLOW, "reviews", "appfollow", "review"),
    (ExternalDataSourceType.JUDGEMEREVIEWS, "reviews", "judgeme_reviews", "review"),
    # OAuth-connected support sources
    (ExternalDataSourceType.INTERCOM, "conversations", "intercom", "ticket"),
    (ExternalDataSourceType.HUBSPOT, "tickets", "hubspot", "ticket"),
]

IDS = [product for _, _, product, _ in TIER1_SOURCES]


def _mock_record(fields: tuple[str, ...]) -> dict:
    """A full record covering every SELECTed column, with plausible types."""
    record: dict = {}
    for field in fields:
        if field in ("tags", "labels"):
            record[field] = '["one", "two"]'
        elif field in ("id", "iid", "project_id", "number", "workflow_state_id"):
            record[field] = 123
        else:
            record[field] = f"value-{field}"
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
    output = config.emitter(1, _mock_record(config.fields))
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
