from dataclasses import replace
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from products.signals.backend.api_deprecation.dispatch import (
    RouteAction,
    build_issue,
    build_task_prompt,
    replace_key_for,
    route_finding,
)
from products.signals.backend.api_deprecation.extractors import EXTRACTORS, extract_pins, is_test_path
from products.signals.backend.api_deprecation.research import build_research_prompt
from products.signals.backend.api_deprecation.scanner import scan_repo
from products.signals.backend.api_deprecation.schema import Classification, Pin, ResearchedDeprecation
from products.signals.backend.api_deprecation.severity import score_severity, select_most_urgent

FIXTURES = Path(__file__).with_name("fixtures")
META = next(e for e in EXTRACTORS if e.vendor == "meta")
GOOGLE = next(e for e in EXTRACTORS if e.vendor == "google_ads")
TODAY = date(2026, 6, 9)


def _pin(vendor: str = "meta", version: str = "v21.0") -> Pin:
    return Pin(
        vendor=vendor,
        product="Meta Graph API (WhatsApp destination)",
        host="graph.facebook.com",
        pinned_version=version,
        file="x/whatsapp.template.ts",
        line=18,
        extractor=vendor,
    )


def _cited(version: str, cutoff: date | None, classification=Classification.MECHANICAL) -> ResearchedDeprecation:
    return ResearchedDeprecation(
        pin=_pin(version=version),
        is_deprecated=True,
        cutoff_date=cutoff,
        recommended_version="v25.0",
        classification=classification,
        evidence_url="https://developers.facebook.com/docs/graph-api/changelog/versions/",
        evidence_quote="v21.0 ... no longer available",
        confidence=0.9,
    )


# --- detector (deterministic) ---


def test_extract_pins_handles_default_variable_form():
    text = "let apiVersion := empty(inputs.api_version) ? 'v21.0' : x\ngraph.facebook.com/{apiVersion}/m"
    pins = extract_pins(text, "whatsapp.template.ts", META)
    assert [(p.pinned_version, p.line) for p in pins] == [("v21.0", 1)]


def test_extract_pins_handles_inline_url_form():
    pins = extract_pins("fetch('https://googleads.googleapis.com/v21/customers/1')", "g.ts", GOOGLE)
    assert [p.pinned_version for p in pins] == ["v21"]


def test_extract_pins_returns_empty_when_host_absent():
    assert extract_pins("no vendor here", "x.ts", META) == []


def test_scan_repo_inventory_excludes_tests():
    extractors = (replace(META, file_globs=("*.template.ts",)), replace(GOOGLE, file_globs=("*.template.ts",)))
    found = {(p.vendor, p.pinned_version) for p in scan_repo(FIXTURES, extractors)}
    assert ("meta", "v21.0") in found and ("google_ads", "v21") in found and ("meta", "v25.0") in found


def test_is_test_path():
    assert is_test_path("a/b.test.ts") and is_test_path("a/test_x.py")
    assert not is_test_path("a/whatsapp.template.ts")


# --- research output: citation enforced, no fabricated dates ---


def test_deprecation_claim_requires_citation():
    raised = False
    try:
        ResearchedDeprecation(pin=_pin(), is_deprecated=True)  # no evidence
    except ValidationError:
        raised = True
    assert raised, "is_deprecated without a citation must be rejected"


def test_non_deprecated_needs_no_citation():
    ok = ResearchedDeprecation(pin=_pin(), is_deprecated=False)
    assert not ok.is_deprecated and ok.evidence_url == ""


# --- severity (from the cited cutoff date, not a seeded table) ---


def test_score_severity_from_cutoff():
    assert score_severity(date(2026, 6, 1), TODAY) == "P0"  # past
    assert score_severity(date(2026, 8, 1), TODAY) == "P1"  # 53 days
    assert score_severity(date(2026, 11, 1), TODAY) == "P2"  # 145 days
    assert score_severity(None, TODAY) == "P3"  # unknown date -> no manufactured urgency


def test_select_most_urgent_orders_by_severity_then_date():
    findings = [_cited("v21", date(2026, 12, 1)), _cited("v20", date(2026, 6, 1)), _cited("v19", None)]
    ordered = select_most_urgent(findings, TODAY)
    assert [f.pin.pinned_version for f in ordered] == ["v20", "v21", "v19"]


# --- research prompt is grounded in the exact pin ---


def test_build_research_prompt_embeds_pin_facts():
    prompt = build_research_prompt(_pin(version="v21.0"))
    assert "v21.0" in prompt and "graph.facebook.com" in prompt and "whatsapp.template.ts" in prompt


# --- dispatch routing (milestone 2): mechanical → PR, structural/low-confidence → human ---


def test_route_skips_non_deprecated():
    assert route_finding(ResearchedDeprecation(pin=_pin(), is_deprecated=False)) == RouteAction.SKIP


def test_route_mechanical_cited_confident_dispatches_pr():
    assert route_finding(_cited("v21.0", date(2026, 6, 1))) == RouteAction.DISPATCH_PR


def test_route_structural_goes_to_human():
    structural = _cited("v21.0", date(2026, 6, 1), classification=Classification.STRUCTURAL)
    assert route_finding(structural) == RouteAction.FILE_ISSUE


def test_route_low_confidence_goes_to_human():
    low = _cited("v21.0", date(2026, 6, 1)).model_copy(update={"confidence": 0.5})
    assert route_finding(low) == RouteAction.FILE_ISSUE


def test_task_prompt_reproduces_chain_for_persisted_pin():
    prompt = build_task_prompt(_cited("v21.0", date(2026, 6, 1)))
    assert "v21.0" in prompt and "v25.0" in prompt and "x/whatsapp.template.ts" in prompt
    assert "update_hog_function_code" in prompt and "--dry-run" in prompt
    assert "DRAFT" in prompt and "#61214" in prompt
    assert "do not open a PR" in prompt  # breaking-change gate


def test_task_prompt_skips_migration_for_runtime_pin():
    pin_runtime = _pin().model_copy(update={"persisted_per_row": False})
    finding = _cited("v21.0", date(2026, 6, 1)).model_copy(update={"pin": pin_runtime})
    assert "No data migration needed" in build_task_prompt(finding)


def test_issue_body_is_cited_and_flagged_for_humans():
    title, body, labels = build_issue(_cited("v21.0", date(2026, 6, 1), classification=Classification.STRUCTURAL))
    assert "needs-human" in labels and "structural" in title
    assert "developers.facebook.com" in body  # evidence carried through


def test_replace_key_mirrors_existing_convention():
    assert replace_key_for(_cited("v21.0", date(2026, 6, 1))) == "meta-api-version-update"


def test_sample_findings_route_as_expected():
    from products.signals.backend.api_deprecation.samples import google_structural_finding, meta_mechanical_finding

    assert route_finding(meta_mechanical_finding()) == RouteAction.DISPATCH_PR
    assert route_finding(google_structural_finding()) == RouteAction.FILE_ISSUE
