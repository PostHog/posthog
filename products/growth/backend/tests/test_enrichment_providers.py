import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.growth.backend.enrichment.providers import HarmonicEnrichmentProvider


def _fake_harmonic_client(company, *, parent_company=None, parent_side_effect=None):
    """Build a mock standing in for `async with AsyncHarmonicClient() as client`."""
    client = MagicMock()
    client.enrich_company_by_domain_strict = AsyncMock(return_value=company)
    client.get_company_by_urn = AsyncMock(return_value=parent_company, side_effect=parent_side_effect)
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


@pytest.mark.asyncio
async def test_enrich_by_domain_prefers_subsidiary_of_over_acquired_by():
    company = {
        "companyType": "STARTUP",
        "relatedCompanies": {
            "acquiredBy": {"companyUrn": "urn:harmonic:company:111"},
            "subsidiaryOf": {"companyUrn": "urn:harmonic:company:222"},
        },
    }
    parent = {"name": "Salesforce", "website": {"domain": "salesforce.com"}}
    cm, client = _fake_harmonic_client(company, parent_company=parent)
    with patch("products.growth.backend.enrichment.providers.AsyncHarmonicClient", return_value=cm):
        lookup = await HarmonicEnrichmentProvider().enrich_by_domain("posthog.com")

    assert lookup.fields is not None
    assert lookup.fields.parent_company == "Salesforce"
    assert lookup.fields.parent_company_domain == "salesforce.com"
    client.get_company_by_urn.assert_awaited_once_with("urn:harmonic:company:222")


@pytest.mark.asyncio
async def test_enrich_by_domain_falls_back_to_acquired_by_when_no_subsidiary_of():
    company = {
        "companyType": "STARTUP",
        "relatedCompanies": {"acquiredBy": {"companyUrn": "urn:harmonic:company:111"}, "subsidiaryOf": None},
    }
    parent = {"name": "Salesforce", "website": {"domain": "salesforce.com"}}
    cm, client = _fake_harmonic_client(company, parent_company=parent)
    with patch("products.growth.backend.enrichment.providers.AsyncHarmonicClient", return_value=cm):
        lookup = await HarmonicEnrichmentProvider().enrich_by_domain("posthog.com")

    assert lookup.fields is not None
    assert lookup.fields.parent_company == "Salesforce"
    client.get_company_by_urn.assert_awaited_once_with("urn:harmonic:company:111")


@pytest.mark.asyncio
async def test_enrich_by_domain_tolerates_missing_related_companies():
    company = {"companyType": "STARTUP"}
    cm, client = _fake_harmonic_client(company)
    with patch("products.growth.backend.enrichment.providers.AsyncHarmonicClient", return_value=cm):
        lookup = await HarmonicEnrichmentProvider().enrich_by_domain("posthog.com")

    assert lookup.fields is not None
    assert lookup.fields.parent_company is None
    assert lookup.fields.parent_company_domain is None
    client.get_company_by_urn.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client_kwargs,expected_captures",
    [
        pytest.param({"parent_side_effect": RuntimeError("boom")}, 1, id="resolution_raises"),
        pytest.param({"parent_company": None}, 0, id="resolution_returns_none"),
        pytest.param({"parent_company": ["not", "a", "dict"]}, 0, id="resolution_returns_non_dict"),
    ],
)
async def test_enrich_by_domain_tolerates_failed_parent_resolution(client_kwargs, expected_captures):
    company = {
        "companyType": "STARTUP",
        "relatedCompanies": {"acquiredBy": {"companyUrn": "urn:harmonic:company:111"}},
    }
    cm, client = _fake_harmonic_client(company, **client_kwargs)
    with (
        patch("products.growth.backend.enrichment.providers.AsyncHarmonicClient", return_value=cm),
        patch("products.growth.backend.enrichment.providers.capture_exception") as mock_capture,
    ):
        lookup = await HarmonicEnrichmentProvider().enrich_by_domain("posthog.com")

    assert lookup.fields is not None
    assert lookup.fields.company_type == "STARTUP"
    assert lookup.fields.parent_company is None
    assert lookup.fields.parent_company_domain is None
    assert mock_capture.call_count == expected_captures


@pytest.mark.asyncio
async def test_enrich_by_domain_skips_parent_resolution_for_empty_urn():
    company = {
        "companyType": "STARTUP",
        "relatedCompanies": {"acquiredBy": {"companyUrn": ""}},
    }
    cm, client = _fake_harmonic_client(company)
    with patch("products.growth.backend.enrichment.providers.AsyncHarmonicClient", return_value=cm):
        lookup = await HarmonicEnrichmentProvider().enrich_by_domain("posthog.com")

    assert lookup.fields is not None
    assert lookup.fields.parent_company is None
    assert lookup.fields.parent_company_domain is None
    client.get_company_by_urn.assert_not_awaited()
