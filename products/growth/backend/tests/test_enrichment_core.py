from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync

from products.growth.backend.enrichment.core import enrich_organization
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.providers import EnrichmentProvider, ProviderLookup
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch


class _FakeProvider(EnrichmentProvider):
    name = "harmonic"

    def __init__(self, lookup: ProviderLookup):
        self._lookup = lookup

    async def enrich_by_domain(self, domain: str) -> ProviderLookup:
        return self._lookup


class TestEnrichmentCore(BaseTest):
    def _enrich(self, lookup: ProviderLookup, is_recheck: bool = False):
        return async_to_sync(enrich_organization)(
            organization_id=str(self.organization.id),
            domain="stripe.com",
            provider=_FakeProvider(lookup),
            pha_client=MagicMock(),
            is_recheck=is_recheck,
        )

    def test_archives_raw_payload_and_writes_live_stores_on_match(self):
        company = {"companyType": "STARTUP", "funding": {"fundingStage": "SEED"}}
        fields = EnrichmentFields(company_type="STARTUP")
        result = self._enrich(ProviderLookup(fields=fields, raw_payload=company))

        assert result is fields
        row = OrganizationEnrichmentFetch.objects.get(organization=self.organization)
        assert row.provider == "harmonic"
        assert row.is_recheck is False
        assert row.payload == company  # verbatim, un-transformed
        assert OrganizationEnrichment.objects.filter(organization=self.organization).exists()

    def test_archives_miss_with_placeholder_and_skips_live_write(self):
        result = self._enrich(ProviderLookup(fields=None, raw_payload=None))

        assert result is None
        row = OrganizationEnrichmentFetch.objects.get(organization=self.organization)
        assert row.payload == {"companyFound": False}
        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()

    def test_recheck_labels_the_archive_row(self):
        self._enrich(ProviderLookup(fields=None, raw_payload=None), is_recheck=True)
        assert OrganizationEnrichmentFetch.objects.get(organization=self.organization).is_recheck is True

    def test_each_fetch_is_a_separate_row(self):
        self._enrich(ProviderLookup(fields=None, raw_payload={"companyFound": False, "n": 1}))
        self._enrich(
            ProviderLookup(fields=EnrichmentFields(company_type="STARTUP"), raw_payload={"n": 2}), is_recheck=True
        )
        rows = OrganizationEnrichmentFetch.objects.filter(organization=self.organization).order_by("fetched_at")
        assert [r.is_recheck for r in rows] == [False, True]

    def test_archive_failure_does_not_break_enrich(self):
        fields = EnrichmentFields(company_type="STARTUP")
        with (
            patch(
                "products.growth.backend.enrichment.writer.OrganizationEnrichmentFetch.objects.create",
                side_effect=RuntimeError("db down"),
            ),
            patch("products.growth.backend.enrichment.writer.capture_exception") as capture_mock,
        ):
            result = self._enrich(ProviderLookup(fields=fields, raw_payload={"companyType": "STARTUP"}))

        assert result is fields
        capture_mock.assert_called_once()
        # The live-store write still happened despite the archive failure.
        assert OrganizationEnrichment.objects.filter(organization=self.organization).exists()
