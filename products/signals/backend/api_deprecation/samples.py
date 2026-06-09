"""Known sample findings for testing the emit → dispatch → PostHog Code path without the sandbox.

These are real, cited findings (the WhatsApp Meta Graph v21.0 case, and a structural Google Ads
example) so you can exercise the back half of the loop deterministically — no changelog research
required. Django-free, so usable from both the management command and tests.
"""

from __future__ import annotations

from datetime import date

from products.signals.backend.api_deprecation.schema import Classification, Pin, ResearchedDeprecation

# Matches what scan_repo finds for the live WhatsApp pin.
_WHATSAPP_PIN = Pin(
    vendor="meta",
    product="Meta Graph API (WhatsApp destination)",
    host="graph.facebook.com",
    pinned_version="v21.0",
    file="nodejs/src/cdp/templates/_destinations/whatsapp/whatsapp.template.ts",
    line=18,
    endpoint="/{version}/{phoneNumberId}/messages",
    extractor="meta",
    persisted_per_row=True,
)

_GOOGLE_ADS_PIN = Pin(
    vendor="google_ads",
    product="Google Ads API (conversions destination)",
    host="googleads.googleapis.com",
    pinned_version="v21",
    file="nodejs/src/cdp/templates/_destinations/google_ads/google.template.ts",
    line=107,
    endpoint="/{version}/customers/{id}:uploadClickConversions",
    extractor="google_ads",
    persisted_per_row=True,
)


def meta_mechanical_finding() -> ResearchedDeprecation:
    """A mechanical, cited finding — should route to a PostHog Code draft PR."""
    return ResearchedDeprecation(
        pin=_WHATSAPP_PIN,
        is_deprecated=True,
        cutoff_date=date(2025, 9, 9),
        already_past_cutoff=True,
        latest_ga_version="v25.0",
        recommended_version="v25.0",
        classification=Classification.MECHANICAL,
        affected_fields=[],
        evidence_url="https://developers.facebook.com/docs/graph-api/changelog/versions/",
        evidence_quote="Calls to Graph API versions older than v22.0 are no longer available.",
        confidence=0.95,
        reasoning="Version-number bump only; the WhatsApp messages payload we send is unchanged across v21→v25.",
    )


def google_structural_finding() -> ResearchedDeprecation:
    """A structural, cited finding — should route to a GitHub issue, never an auto-PR."""
    return ResearchedDeprecation(
        pin=_GOOGLE_ADS_PIN,
        is_deprecated=True,
        cutoff_date=date(2026, 11, 1),
        latest_ga_version="v22",
        recommended_version="v22",
        classification=Classification.STRUCTURAL,
        affected_fields=["uploadClickConversions endpoint relocated to the Data Manager API"],
        evidence_url="https://developers.google.com/google-ads/api/docs/sunset-dates",
        evidence_quote="Conversion uploads move to the Data Manager API.",
        confidence=0.8,
        reasoning="The conversion-upload endpoint we use changed surface — needs a human to scope the migration.",
    )


SAMPLES = {
    "meta": meta_mechanical_finding,
    "google-structural": google_structural_finding,
}
