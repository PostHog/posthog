from dataclasses import replace
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from products.signals.backend.api_deprecation.extractors import EXTRACTORS, extract_pins, is_test_path
from products.signals.backend.api_deprecation.research import build_research_initial_prompt
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


# --- research prompt is grounded in the detected pins ---


def test_build_research_initial_prompt_embeds_pins():
    prompt = build_research_initial_prompt([_pin(version="v21.0")])
    assert "v21.0" in prompt and "graph.facebook.com" in prompt and "whatsapp.template.ts" in prompt
