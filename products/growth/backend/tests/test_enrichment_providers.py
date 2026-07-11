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
async def test_enrich_by_domain_transforms_response():
    cm, client = _fake_harmonic_client({"companyType": "STARTUP", "funding": {"fundingStage": "SEED"}})
    with patch("products.growth.backend.enrichment.providers.AsyncHarmonicClient", return_value=cm):
        fields = await HarmonicEnrichmentProvider().enrich_by_domain("posthog.com")

    assert fields is not None
    assert fields.company_type == "STARTUP"
    assert fields.funding_stage == "SEED"
    client.enrich_company_by_domain_strict.assert_awaited_once_with("posthog.com")


@pytest.mark.asyncio
async def test_enrich_by_domain_returns_none_when_company_not_found():
    cm, _ = _fake_harmonic_client(None)
    with patch("products.growth.backend.enrichment.providers.AsyncHarmonicClient", return_value=cm):
        fields = await HarmonicEnrichmentProvider().enrich_by_domain("unknown.example")

    assert fields is None
