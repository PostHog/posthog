from datetime import date
from pathlib import Path

import pytest

from pydantic import ValidationError

from products.signals.backend.api_deprecation.extractors import extract_usages, is_test_path
from products.signals.backend.api_deprecation.research import build_research_initial_prompt
from products.signals.backend.api_deprecation.scanner import ScanTarget, scan_repo
from products.signals.backend.api_deprecation.schema import (
    ApiUsage,
    Classification,
    ResearchedDeprecation,
    ResearchedDeprecationList,
)
from products.signals.backend.api_deprecation.severity import score_severity, select_most_urgent

FIXTURES = Path(__file__).parents[1] / "api_deprecation" / "fixtures"
TODAY = date(2026, 6, 9)
# Recursive glob so the scan reaches the nested fixtures/nested/tests/ file.
_TARGETS = (ScanTarget("**/*.template.ts", persisted_per_row=True),)


def _usage(version: str | None = "v21.0", endpoint: str = "/{…}/{…}/messages") -> ApiUsage:
    return ApiUsage(
        host="graph.facebook.com",
        endpoint=endpoint,
        version=version,
        file="x/whatsapp.template.ts",
        line=18,
        extractor="url",
    )


def _cited(
    version: str,
    cutoff: date | None,
    classification: Classification = Classification.MECHANICAL,
) -> ResearchedDeprecation:
    return ResearchedDeprecation(
        usage=_usage(version=version),
        is_deprecated=True,
        headline=f"Bump Meta Graph API {version} → v25.0",
        cutoff_date=cutoff,
        recommended_version="v25.0",
        classification=classification,
        evidence_url="https://developers.facebook.com/docs/graph-api/changelog/versions/",
        evidence_quote="v21.0 ... no longer available",
        confidence=0.9,
    )


# --- detector (deterministic) ---


def test_extract_endpoint_survives_interpolation_with_nested_quotes():
    # The Google Ads regression: `:uploadClickConversions` follows an interpolation containing
    # quotes — a quote-terminated regex would lose exactly the endpoint research needs.
    text = "let res := fetch(f'https://googleads.googleapis.com/v21/customers/{splitByString('/', inputs.customerId)[1]}:uploadClickConversions', {})"
    usages = extract_usages(text, "google.template.ts")
    assert [(u.host, u.endpoint, u.version) for u in usages] == [
        ("googleads.googleapis.com", "/v21/customers/{…}:uploadClickConversions", "v21")
    ]


def test_extract_attaches_variable_form_version():
    text = "let apiVersion := empty(inputs.api_version) ? 'v21.0' : x\nlet url := f'https://graph.facebook.com/{apiVersion}/{id}/messages'"
    usages = extract_usages(text, "whatsapp.template.ts")
    assert [(u.endpoint, u.version, u.extractor) for u in usages] == [
        ("/{…}/{…}/messages", "v21.0", "url+variable-version")
    ]


def test_extract_keeps_unversioned_usages():
    usages = extract_usages("fetch('https://slack.com/api/chat.postMessage')", "s.ts")
    assert [(u.host, u.endpoint, u.version) for u in usages] == [("slack.com", "/api/chat.postMessage", None)]


def test_extract_keeps_doc_links_for_agent_triage():
    # Non-comment doc links stay in the inventory — deciding they are not API calls is the
    # research agent's triage job, not the detector's.
    usages = extract_usages("description: 'See https://help.brevo.com/hc/articles/209467485'", "b.ts")
    assert [u.host for u in usages] == ["help.brevo.com"]


@pytest.mark.parametrize(
    "text",
    [
        "// see https://developers.google.com/google-ads/api/docs",  # comment line
        "# https://developers.facebook.com/docs/graph-api",  # python comment
        "let url := 'https://us.i.posthog.com/capture'",  # our own host
        "let url := 'https://example.com/v1/things'",  # placeholder host
        "no urls here",
    ],
)
def test_extract_skips_non_usages(text: str):
    assert extract_usages(text, "x.ts") == []


def test_extract_dedupes_repeated_usage_first_line_wins():
    text = "fetch('https://api.attio.com/v2/objects')\nfetch('https://api.attio.com/v2/objects')"
    usages = extract_usages(text, "a.ts")
    assert [(u.endpoint, u.line) for u in usages] == [("/v2/objects", 1)]


def test_scan_repo_reports_the_inventory():
    found = {(u.host, u.version) for u in scan_repo(FIXTURES, _TARGETS)}
    assert {
        ("googleads.googleapis.com", "v21"),
        ("graph.facebook.com", "v21.0"),
        ("graph.facebook.com", "v25.0"),
    } <= found
    # The doc link in the google fixture's input description is inventoried for agent triage...
    assert ("support.google.com", None) in found
    # ...but our own host is not.
    assert not any(host.endswith("posthog.com") for host, _ in found)


def test_scan_repo_excludes_test_files():
    # fixtures/nested/tests/stale.template.ts uses v19.0 but lives under a tests/ dir → excluded by default.
    versions = {(u.host, u.version) for u in scan_repo(FIXTURES, _TARGETS)}
    assert ("graph.facebook.com", "v19.0") not in versions
    assert ("graph.facebook.com", "v19.0") in {
        (u.host, u.version) for u in scan_repo(FIXTURES, _TARGETS, include_test_files=True)
    }


def test_scan_repo_sets_persisted_per_row_from_target():
    # CDP templates bake into HogFunction rows (data migration needed); plain source code does not.
    plain = (ScanTarget("google.template.ts", persisted_per_row=False),)
    assert all(not u.persisted_per_row for u in scan_repo(FIXTURES, plain))
    assert all(u.persisted_per_row for u in scan_repo(FIXTURES, _TARGETS))


@pytest.mark.parametrize(
    "path,expected",
    [
        ("a/b.test.ts", True),
        ("a/test_x.py", True),
        ("a/tests/x.py", True),
        ("a/whatsapp.template.ts", False),
    ],
)
def test_is_test_path(path: str, expected: bool):
    assert is_test_path(path) is expected


# --- research output: citation enforced, no fabricated findings ---


@pytest.mark.parametrize(
    "missing_field",
    ["evidence_url", "evidence_quote", "headline"],
)
def test_deprecation_claim_requires_citation_and_headline(missing_field: str):
    kwargs = {
        "headline": "Bump Meta Graph API v21.0 → v25.0",
        "evidence_url": "https://developers.facebook.com/docs/graph-api/changelog/",
        "evidence_quote": "v21.0 ... no longer available",
    }
    kwargs[missing_field] = ""
    with pytest.raises(ValidationError):
        ResearchedDeprecation(usage=_usage(), is_deprecated=True, **kwargs)


def test_triage_lists_need_no_citation():
    out = ResearchedDeprecationList(cleared=["slack.com/api/chat.postMessage"], skipped=["help.brevo.com/hc"])
    assert out.items == [] and len(out.cleared) == 1 and len(out.skipped) == 1


# --- severity (from the cited cutoff date, not a seeded table) ---


@pytest.mark.parametrize(
    "cutoff,expected",
    [
        (date(2026, 6, 1), "P0"),  # past — vendor already blocks the usage
        (date(2026, 6, 9), "P0"),  # cutoff is today — blocked as of now
        (date(2026, 6, 20), "P1"),  # imminent but future — impact, not breakage yet
        (date(2026, 8, 1), "P1"),  # 53 days
        (date(2026, 11, 1), "P2"),  # 145 days
        (None, "P3"),  # unknown date -> no manufactured urgency
    ],
)
def test_score_severity_from_cutoff(cutoff: date | None, expected: str):
    assert score_severity(cutoff, TODAY) == expected


def test_select_most_urgent_orders_by_severity_then_date():
    findings = [_cited("v21", date(2026, 12, 1)), _cited("v20", date(2026, 6, 1)), _cited("v19", None)]
    ordered = select_most_urgent(findings, TODAY)
    assert [f.usage.version for f in ordered] == ["v20", "v21", "v19"]


# --- research prompt is grounded in the detected usages ---


def test_build_research_initial_prompt_embeds_usages_as_verbatim_json():
    # The agent's research output must echo each usage verbatim, so the inventory has to carry
    # every ApiUsage field as copyable JSON.
    usage = _usage()
    prompt = build_research_initial_prompt([usage])
    assert usage.model_dump_json() in prompt
    assert "graph.facebook.com" in prompt and "whatsapp.template.ts" in prompt


def test_agent_class_loads_via_production_import_path():
    # The Temporal activity imports the agent dynamically by dotted path; a module move that
    # misses this wiring would only fail at runtime without this check.
    from products.signals.backend.custom_agent.loader import import_agent_class  # noqa: PLC0415 — Django-only dep

    agent_class = import_agent_class("products.signals.backend.api_deprecation.agent.ApiDeprecationAgent")
    assert agent_class.identifier() == ("signals", "api_deprecation")
