import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.growth.backend.enrichment.providers import HarmonicEnrichmentProvider


def _fake_harmonic_client(company):
    """Build a mock standing in for `async with AsyncHarmonicClient() as client`."""
    client = MagicMock()
    client.enrich_company_by_domain_strict = AsyncMock(return_value=company)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, client


@pytest.mark.asyncio
async def test_enrich_by_domain_transforms_response_and_keeps_raw_payload():
    company = {"companyType": "STARTUP", "funding": {"fundingStage": "SEED"}}
    cm, client = _fake_harmonic_client(company)
    with patch("products.growth.backend.enrichment.providers.AsyncHarmonicClient", return_value=cm):
        lookup = await HarmonicEnrichmentProvider().enrich_by_domain("posthog.com")

    assert lookup.fields is not None
    assert lookup.fields.company_type == "STARTUP"
    assert lookup.fields.funding_stage == "SEED"
    # The raw provider response is preserved verbatim for the archive.
    assert lookup.raw_payload == company
    client.enrich_company_by_domain_strict.assert_awaited_once_with("posthog.com")


@pytest.mark.asyncio
async def test_enrich_by_domain_returns_no_fields_and_no_payload_when_company_not_found():
    cm, _ = _fake_harmonic_client(None)
    with patch("products.growth.backend.enrichment.providers.AsyncHarmonicClient", return_value=cm):
        lookup = await HarmonicEnrichmentProvider().enrich_by_domain("unknown.example")

    assert lookup.fields is None
    assert lookup.raw_payload is None
