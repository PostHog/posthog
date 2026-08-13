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
        # First attempt: Clay's bridge columns are already present, so they feed the score too —
        # but the person mirror is recheck-only, so `set` stays unused.
        pha_client = MagicMock()
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021, ownership_status="PRIVATE")
        self._enrich(
            ProviderLookup(fields=fields, raw_payload={"n": 1}),
            role_at_organization="Founder",
            clay=ClayBridgeInputs(est_revenue=25_000_000, clay_processed=True),
            pha_client=pha_client,
            distinct_id="signer-distinct-id",
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 21
        assert record.data["icp_score_version"] == "clay-parity-2"
        properties = pha_client.group_identify.call_args.kwargs["properties"]
        assert properties["icp_score"] == 21
        assert properties["icp_score_version"] == "clay-parity-2"
        pha_client.set.assert_not_called()

    def test_first_attempt_scores_without_waiting_for_clay(self):
        # Clay's bridge write lands after ours more often than not, so the first attempt scores
        # on our fields alone (clay_processed=False) rather than waiting for the recheck.
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        result = self._enrich(ProviderLookup(fields=fields, raw_payload={"n": 1}), role_at_organization="engineering")

        assert result is fields
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        assert record.data["icp_score_version"] == "clay-parity-2"

    def test_first_attempt_miss_reconstructs_fields_from_a_prior_record_and_scores(self):
        # A re-dispatched first attempt (e.g. via the backfill command) can land on an org that
        # already carries a partial record; it must score from that record just like a recheck
        # would, without mirroring onto the person (mirror stays recheck-only).
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={"headcount": 750, "country": "US", "founded_year": 2021, "company_type_deterministic": "yc"},
        )
        pha_client = MagicMock()

        result = self._enrich(
            ProviderLookup(fields=None, raw_payload=None),
            role_at_organization="engineering",
            pha_client=pha_client,
            distinct_id="signer-distinct-id",
        )

        assert result is None
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        pha_client.set.assert_not_called()

    def test_first_attempt_miss_with_only_first_party_data_does_not_score(self):
        # The work_email row written before every dispatch must not count as prior provider data.
        OrganizationEnrichment.objects.create(organization=self.organization, data={"work_email": True})
        pha_client = MagicMock()

        result = self._enrich(ProviderLookup(fields=None, raw_payload=None), pha_client=pha_client)

        assert result is None
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert "icp_score" not in record.data
        pha_client.group_identify.assert_not_called()

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

    def test_first_attempt_does_not_look_up_the_person(self):
        # The Clearbit hog function and the mirror check both need the signer's person, but
        # neither is recheck-independent — a first-attempt lookup would usually just read a
        # not-yet-written profile.
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        with (
            patch("products.growth.backend.enrichment.core.read_clay_bridge_inputs", return_value=ClayBridgeInputs()),
            patch("products.growth.backend.enrichment.core.get_person_by_distinct_id") as person_mock,
        ):
            async_to_sync(enrich_organization)(
                organization_id=str(self.organization.id),
                domain="stripe.com",
                provider=_FakeProvider(ProviderLookup(fields=fields, raw_payload={"n": 1})),
                pha_client=MagicMock(),
                is_recheck=False,
                role_at_organization="engineering",
                distinct_id="signer-distinct-id",
            )

        person_mock.assert_not_called()

    def test_recheck_person_lookup_failure_still_scores_from_non_clearbit_inputs(self):
        pha_client = MagicMock()
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        self._enrich(
            ProviderLookup(fields=fields, raw_payload={"n": 1}),
            is_recheck=True,
            role_at_organization="engineering",
            pha_client=pha_client,
            distinct_id="signer-distinct-id",
            person=RuntimeError("personhog down"),
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        pha_client.set.assert_not_called()

    @parameterized.expand(
        [
            (
                "clay_wins_when_both_present",
                ClayBridgeInputs(est_revenue=5_000_000),
                {"clearbit": {"company": {"metrics": {"estimatedAnnualRevenue": "$100M-$250M"}}}},
                6,
            ),
            (
                "clearbit_fills_in_when_clay_is_absent",
                ClayBridgeInputs(),
                {"clearbit": {"company": {"metrics": {"estimatedAnnualRevenue": "$1M-$10M"}}}},
                6,
            ),
            (
                "clay_zero_revenue_falls_back_to_clearbit",
                # Clay's own _numeric coerces a written 0 (or "0") into 0.0, which the formula's
                # strict bands treat exactly like a missing value — it must not shadow Clearbit's.
                ClayBridgeInputs(est_revenue=0.0),
                {"clearbit": {"company": {"metrics": {"estimatedAnnualRevenue": "$1M-$10M"}}}},
                6,
            ),
            ("both_absent_scores_neither_branch", ClayBridgeInputs(), {}, 0),
        ]
    )
    def test_clearbit_fallback_composition_precedence(self, _name, clay, person_properties, expected_score):
        fields = EnrichmentFields(country="US")
        self._enrich(
            ProviderLookup(fields=fields, raw_payload={"n": 1}),
            is_recheck=True,
            clay=clay,
            distinct_id="signer-distinct-id",
            person=MagicMock(properties=person_properties),
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == expected_score

    @parameterized.expand(
        [
            ("private", "PRIVATE", 3),
            ("public", "PUBLIC", 0),
            ("acquired_or_merged", "ACQUIRED_OR_MERGED", 0),
            ("active", "ACTIVE", 0),
            ("out_of_business", "OUT_OF_BUSINESS", 0),
            ("absent", None, 0),
        ]
    )
    def test_only_private_ownership_status_scores_the_company_type_term(self, _name, ownership_status, expected_score):
        fields = EnrichmentFields(country="US", ownership_status=ownership_status)
        self._enrich(ProviderLookup(fields=fields, raw_payload={"n": 1}))

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == expected_score

    def test_clearbit_fallback_does_not_block_the_mirror(self):
        pha_client = MagicMock()
        fields = EnrichmentFields(country="US")
        self._enrich(
            ProviderLookup(fields=fields, raw_payload={"n": 1}),
            is_recheck=True,
            clay=ClayBridgeInputs(),
            distinct_id="signer-distinct-id",
            person=MagicMock(properties={"clearbit": {"company": {"metrics": {"estimatedAnnualRevenue": "$1M-$10M"}}}}),
            pha_client=pha_client,
        )

        pha_client.set.assert_called_once()
        assert pha_client.set.call_args.kwargs["properties"]["icp_score"] == 6

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

    def test_bridge_read_failure_still_scores_from_own_fields(self):
        # The bridge is optional input, so a failed READ scores exactly like an empty bridge
        # instead of costing the score entirely (a transient store error would otherwise leave
        # the org score-less until the next attempt).
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        with patch("products.growth.backend.enrichment.core.capture_exception") as capture_mock:
            result = self._enrich(
                ProviderLookup(fields=fields, raw_payload={"n": 1}),
                role_at_organization="engineering",
                clay=RuntimeError("group store down"),
            )

        assert result is fields
        capture_mock.assert_called_once()
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        assert record.data["headcount"] == 750

    def test_bridge_read_failure_never_downgrades_a_persisted_score(self):
        # A persisted score may have been computed WITH bridge data (revenue, company type);
        # a bridge-less recompute at recheck would silently strip those points.
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={"icp_score": 15, "icp_score_version": "clay-parity-1", "headcount": 750},
        )
        fields = EnrichmentFields(headcount=800, country="US", founded_year=2021)

        result = self._enrich(
            ProviderLookup(fields=fields, raw_payload={"n": 1}),
            is_recheck=True,
            role_at_organization="engineering",
            clay=RuntimeError("group store down"),
        )

        assert result is fields
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 15
        assert record.data["headcount"] == 800

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
