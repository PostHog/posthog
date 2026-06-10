from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

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
# Recursive globs so the scan reaches the nested fixtures/nested/tests/ file.
_RECURSIVE = (replace(META, file_globs=("**/*.template.ts",)), replace(GOOGLE, file_globs=("**/*.template.ts",)))


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


def test_scan_repo_reports_the_inventory():
    found = {(p.vendor, p.pinned_version) for p in scan_repo(FIXTURES, _RECURSIVE)}
    assert {("meta", "v21.0"), ("google_ads", "v21"), ("meta", "v25.0")} <= found


def test_scan_repo_excludes_test_files():
    # fixtures/nested/tests/stale.template.ts pins v19.0 but lives under a tests/ dir → excluded by default.
    versions = {(p.vendor, p.pinned_version) for p in scan_repo(FIXTURES, _RECURSIVE)}
    assert ("meta", "v19.0") not in versions
    assert ("meta", "v19.0") in {
        (p.vendor, p.pinned_version) for p in scan_repo(FIXTURES, _RECURSIVE, include_test_files=True)
    }


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


# --- research output: citation enforced, no fabricated dates ---


def test_deprecation_claim_requires_citation():
    with pytest.raises(ValidationError):
        ResearchedDeprecation(pin=_pin(), is_deprecated=True)  # no evidence


def test_non_deprecated_needs_no_citation():
    ok = ResearchedDeprecation(pin=_pin(), is_deprecated=False)
    assert not ok.is_deprecated and ok.evidence_url == ""


# --- severity (from the cited cutoff date, not a seeded table) ---


@pytest.mark.parametrize(
    "cutoff,expected",
    [
        (date(2026, 6, 1), "P0"),  # past
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
    assert [f.pin.pinned_version for f in ordered] == ["v20", "v21", "v19"]


# --- research prompt is grounded in the detected pins ---


def test_build_research_initial_prompt_embeds_pins():
    prompt = build_research_initial_prompt([_pin(version="v21.0")])
    assert "v21.0" in prompt and "graph.facebook.com" in prompt and "whatsapp.template.ts" in prompt
