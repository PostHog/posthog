from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.growth.backend.enrichment.bridge import ClayBridgeInputs
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
    def _enrich(
        self,
        lookup: ProviderLookup,
        is_recheck: bool = False,
        role_at_organization=None,
        clay=None,
        pha_client=None,
        distinct_id=None,
        person=None,
        geoip_country_code=None,
    ):
        person_patch_kwargs = {"side_effect": person} if isinstance(person, Exception) else {"return_value": person}
        clay_patch_kwargs = (
            {"side_effect": clay} if isinstance(clay, Exception) else {"return_value": clay or ClayBridgeInputs()}
        )
        with (
            patch("products.growth.backend.enrichment.core.read_clay_bridge_inputs", **clay_patch_kwargs),
            patch("products.growth.backend.enrichment.core.get_person_by_distinct_id", **person_patch_kwargs),
        ):
            return async_to_sync(enrich_organization)(
                organization_id=str(self.organization.id),
                domain="stripe.com",
                provider=_FakeProvider(lookup),
                pha_client=pha_client or MagicMock(),
                is_recheck=is_recheck,
                role_at_organization=role_at_organization,
                geoip_country_code=geoip_country_code,
                distinct_id=distinct_id,
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

    def test_scores_the_org_from_our_fields_the_signup_role_and_clays_columns(self):
        # First attempt: scores immediately because Clay has already processed the org
        # (clay_processed=True) — but the person mirror is recheck-only, so `set` stays unused.
        pha_client = MagicMock()
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        self._enrich(
            ProviderLookup(fields=fields, raw_payload={"n": 1}),
            role_at_organization="Founder",
            clay=ClayBridgeInputs(est_revenue=25_000_000, company_type="private", clay_processed=True),
            pha_client=pha_client,
            distinct_id="signer-distinct-id",
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 21
        assert record.data["icp_score_version"] == "clay-parity-1"
        properties = pha_client.group_identify.call_args.kwargs["properties"]
        assert properties["icp_score"] == 21
        assert properties["icp_score_version"] == "clay-parity-1"
        pha_client.set.assert_not_called()

    def test_first_attempt_before_clay_has_processed_the_org_writes_no_score(self):
        # Clay's bridge write lands after ours more often than not, so a first attempt with
        # clay_processed=False must skip scoring entirely rather than write a too-low score.
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        self._enrich(ProviderLookup(fields=fields, raw_payload={"n": 1}), role_at_organization="engineering")

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert "icp_score" not in record.data
        assert "icp_score_version" not in record.data
        assert record.data["headcount"] == 750

    def test_recheck_scores_unconditionally_even_when_clay_never_processed(self):
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        self._enrich(
            ProviderLookup(fields=fields, raw_payload={"n": 1}), is_recheck=True, role_at_organization="engineering"
        )

        # No Clay columns: the revenue and company-type branches simply do not score.
        assert OrganizationEnrichment.objects.get(organization=self.organization).data["icp_score"] == 12

    @parameterized.expand(
        [
            ("geoip_fills_missing_provider_country", None, "US", 12, "US"),
            ("provider_country_wins_over_geoip", "DE", "BR", 12, "DE"),
            ("both_missing_keeps_the_penalty", None, None, 7, None),
        ]
    )
    def test_country_falls_back_to_signup_geoip(self, _name, provider_country, geoip_country, score, stored_country):
        pha_client = MagicMock()
        fields = EnrichmentFields(headcount=750, country=provider_country, founded_year=2021)
        self._enrich(
            ProviderLookup(fields=fields, raw_payload={"n": 1}),
            is_recheck=True,
            role_at_organization="engineering",
            geoip_country_code=geoip_country,
            pha_client=pha_client,
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == score
        assert record.data.get("country") == stored_country
        properties = pha_client.group_identify.call_args.kwargs["properties"]
        assert properties.get("icp_country") == stored_country

    def test_no_person_write_without_a_distinct_id(self):
        # Scoring happens (recheck), but with no distinct_id there is no one to mirror onto.
        pha_client = MagicMock()
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        self._enrich(ProviderLookup(fields=fields, raw_payload={"n": 1}), is_recheck=True, pha_client=pha_client)

        pha_client.group_identify.assert_called_once()
        pha_client.set.assert_not_called()

    @parameterized.expand(
        [
            ("no_prior_person", None, True),
            ("person_with_no_icp_score", MagicMock(properties={}), True),
            ("person_with_clay_owned_score", MagicMock(properties={"icp_score": 18}), False),
            (
                "person_with_our_own_versioned_score",
                MagicMock(properties={"icp_score": 9, "icp_score_version": "clay-parity-1"}),
                True,
            ),
            ("person_lookup_raises", RuntimeError("personhog down"), False),
        ]
    )
    def test_recheck_mirror_policy(self, _name, person, expect_mirror):
        pha_client = MagicMock()
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        self._enrich(
            ProviderLookup(fields=fields, raw_payload={"n": 1}),
            is_recheck=True,
            pha_client=pha_client,
            distinct_id="signer-distinct-id",
            person=person,
        )

        assert pha_client.set.called is expect_mirror

    def test_recheck_miss_reconstructs_fields_from_the_prior_record_and_scores(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={"headcount": 750, "country": "US", "founded_year": 2021, "company_type_deterministic": "yc"},
        )

        result = self._enrich(
            ProviderLookup(fields=None, raw_payload=None), is_recheck=True, role_at_organization="engineering"
        )

        # Matches the provider-lookup miss, not the fallback score write — the workflow's
        # matched/upgraded reporting tracks the provider lookup, not this backstop.
        assert result is None
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        assert record.data["company_type_deterministic"] == "yc"

    def test_recheck_miss_with_no_prior_record_writes_nothing(self):
        result = self._enrich(ProviderLookup(fields=None, raw_payload=None), is_recheck=True)

        assert result is None
        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()

    def test_recheck_miss_with_only_first_party_data_does_not_score(self):
        # Every signup gets a work_email row before enrichment runs; it must not count as prior
        # provider data, or every never-matched org would be scored on empty firmographics.
        OrganizationEnrichment.objects.create(organization=self.organization, data={"work_email": True})
        pha_client = MagicMock()

        result = self._enrich(ProviderLookup(fields=None, raw_payload=None), is_recheck=True, pha_client=pha_client)

        assert result is None
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert "icp_score" not in record.data
        pha_client.group_identify.assert_not_called()

    def test_bridge_read_failure_writes_no_score_rather_than_a_low_one(self):
        fields = EnrichmentFields(headcount=750, country="US")
        with patch("products.growth.backend.enrichment.core.capture_exception") as capture_mock:
            result = self._enrich(
                ProviderLookup(fields=fields, raw_payload={"n": 1}),
                is_recheck=True,
                clay=RuntimeError("group store down"),
            )

        assert result is fields
        capture_mock.assert_called_once()
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert "icp_score" not in record.data
        assert record.data["headcount"] == 750

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
