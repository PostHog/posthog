from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.growth.backend.enrichment.bridge import ClayBridgeInputs
from products.growth.backend.enrichment.core import enrich_organization
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.icp_lists import clear_lists_cache
from products.growth.backend.enrichment.providers import EnrichmentProvider, ProviderLookup
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch


class _FakeProvider(EnrichmentProvider):
    name = "harmonic"

    def __init__(self, lookup: ProviderLookup):
        self._lookup = lookup

    async def enrich_by_domain(self, domain: str) -> ProviderLookup:
        return self._lookup


# A GraphQL-shaped company the fit score maxes with the test lists: traction 35 (120k
# visits, +71% 90d), capital 30 ($12M + YC), AI 15 (tag), headcount growth 10 (+50% 180d),
# software 10 (eng headcount).
def _company(**overrides):
    company = {
        "companyType": "STARTUP",
        "headcount": 12,
        "description": "AI developer platform",
        "funding": {"fundingTotal": 12_000_000, "investors": [{"name": "Y Combinator"}]},
        "tagsV2": [
            {"displayValue": "Artificial Intelligence", "type": "MARKET"},
            {"displayValue": "S25", "type": "YC_BATCH"},
        ],
        "tractionMetrics": {
            "webTraffic": {
                "latestMetricValue": 120_000,
                "metrics": [
                    {"timestamp": "2026-08-01T00:00:00Z", "metricValue": 120_000},
                    {"timestamp": "2026-04-01T00:00:00Z", "metricValue": 70_000},
                ],
            },
            "headcount": {
                "latestMetricValue": 12,
                "metrics": [
                    {"timestamp": "2026-08-01T00:00:00Z", "metricValue": 12},
                    {"timestamp": "2026-01-01T00:00:00Z", "metricValue": 8},
                ],
            },
            "headcountEngineering": {"latestMetricValue": 8, "metrics": []},
        },
    }
    company.update(overrides)
    return company


# Matched but empty-shell: no headcount, no funding, no investors, no tags, no traffic.
def _empty_shell():
    return {"companyType": "STARTUP", "funding": {}, "tagsV2": [], "tractionMetrics": {}}


class TestEnrichmentCore(BaseTest):
    def setUp(self):
        super().setUp()
        IcpScoringConfig.objects.create(
            version="test-lists-1",
            tags=[
                {"tag": "Artificial Intelligence", "recommendation": "ai_positive"},
                {"tag": "Developer Tools", "recommendation": "software_positive"},
            ],
            quality_investors=[{"investor": "Y Combinator", "aliases": ["YC"]}],
            is_active=True,
        )
        clear_lists_cache()

    def tearDown(self):
        clear_lists_cache()
        super().tearDown()

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
        domain="stripe.com",
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
                domain=domain,
                provider=_FakeProvider(lookup),
                pha_client=pha_client or MagicMock(),
                is_recheck=is_recheck,
                role_at_organization=role_at_organization,
                geoip_country_code=geoip_country_code,
                distinct_id=distinct_id,
            )

    # ---------- archive + legacy clay behavior (unchanged contracts) ----------

    def test_archives_raw_payload_and_writes_live_stores_on_match(self):
        company = {"companyType": "STARTUP", "funding": {"fundingStage": "SEED"}}
        fields = EnrichmentFields(company_type="STARTUP")
        outcome = self._enrich(ProviderLookup(fields=fields, raw_payload=company))

        assert outcome.provider_fields is fields
        row = OrganizationEnrichmentFetch.objects.get(organization=self.organization)
        assert row.provider == "harmonic"
        assert row.is_recheck is False
        assert row.payload == company  # verbatim, un-transformed
        assert OrganizationEnrichment.objects.filter(organization=self.organization).exists()

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

    def test_clay_scores_from_our_fields_the_signup_role_and_clays_columns(self):
        # First attempt: Clay's bridge columns are already present, so they feed the clay
        # score too — but the clay person mirror is recheck-only, so the only person write
        # is the fit mirror, and this payload's fit evaluation is score-less (insufficient).
        pha_client = MagicMock()
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021, ownership_status="PRIVATE")
        self._enrich(
            ProviderLookup(fields=fields, raw_payload=_empty_shell()),
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
        pha_client.set.assert_called_once_with(
            distinct_id="signer-distinct-id", properties={"icp_fit_status": "insufficient_data"}
        )

    def test_clay_first_attempt_scores_without_waiting_for_clay(self):
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        outcome = self._enrich(
            ProviderLookup(fields=fields, raw_payload=_empty_shell()), role_at_organization="engineering"
        )

        assert outcome.provider_fields is fields
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        assert record.data["icp_score_version"] == "clay-parity-2"

    def test_first_attempt_miss_reconstructs_fields_from_a_prior_record_and_clay_scores(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={"headcount": 750, "country": "US", "founded_year": 2021, "company_type_deterministic": "yc"},
        )
        pha_client = MagicMock()

        outcome = self._enrich(
            ProviderLookup(fields=None, raw_payload=None),
            role_at_organization="engineering",
            pha_client=pha_client,
            distinct_id="signer-distinct-id",
        )

        assert outcome.provider_fields is None
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        assert record.data["company_type_deterministic"] == "yc"
        pha_client.set.assert_called_once_with(
            distinct_id="signer-distinct-id", properties={"icp_fit_status": "not_found"}
        )

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
            ProviderLookup(fields=fields, raw_payload=_empty_shell()),
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

    def test_country_falls_back_to_the_record_when_the_caller_has_no_geoip(self):
        OrganizationEnrichment.objects.update_or_create(
            organization=self.organization, defaults={"data": {"country": "DE", "work_email": True}}
        )
        pha_client = MagicMock()

        self._enrich(
            ProviderLookup(
                fields=EnrichmentFields(headcount=750, country=None, founded_year=2021), raw_payload=_empty_shell()
            ),
            is_recheck=True,
            role_at_organization="engineering",
            geoip_country_code=None,
            pha_client=pha_client,
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data.get("country") == "DE"
        assert record.data["icp_score"] == 12

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
    def test_clay_recheck_mirror_policy(self, _name, person, expect_mirror):
        # Empty-shell payload keeps the fit evaluation score-less, and the fit mirror always
        # sends its status regardless of person state, so isolate the guarded clay mirror by
        # its own key rather than asserting on `set` calls overall.
        pha_client = MagicMock()
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        self._enrich(
            ProviderLookup(fields=fields, raw_payload=_empty_shell()),
            is_recheck=True,
            pha_client=pha_client,
            distinct_id="signer-distinct-id",
            person=person,
        )

        clay_calls = [c for c in pha_client.set.call_args_list if "icp_score" in c.kwargs["properties"]]
        assert bool(clay_calls) is expect_mirror

    def test_first_attempt_does_not_look_up_the_person(self):
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        with (
            patch("products.growth.backend.enrichment.core.read_clay_bridge_inputs", return_value=ClayBridgeInputs()),
            patch("products.growth.backend.enrichment.core.get_person_by_distinct_id") as person_mock,
        ):
            async_to_sync(enrich_organization)(
                organization_id=str(self.organization.id),
                domain="stripe.com",
                provider=_FakeProvider(ProviderLookup(fields=fields, raw_payload=_empty_shell())),
                pha_client=MagicMock(),
                is_recheck=False,
                role_at_organization="engineering",
                distinct_id="signer-distinct-id",
            )

        person_mock.assert_not_called()

    def test_bridge_read_failure_still_clay_scores_from_own_fields(self):
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        with patch("products.growth.backend.enrichment.core.capture_exception") as capture_mock:
            outcome = self._enrich(
                ProviderLookup(fields=fields, raw_payload=_empty_shell()),
                role_at_organization="engineering",
                clay=RuntimeError("group store down"),
            )

        assert outcome.provider_fields is fields
        capture_mock.assert_called_once()
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        assert record.data["headcount"] == 750

    def test_bridge_read_failure_never_downgrades_a_persisted_clay_score(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={"icp_score": 15, "icp_score_version": "clay-parity-1", "headcount": 750},
        )
        fields = EnrichmentFields(headcount=800, country="US", founded_year=2021)

        outcome = self._enrich(
            ProviderLookup(fields=fields, raw_payload=_empty_shell()),
            is_recheck=True,
            role_at_organization="engineering",
            clay=RuntimeError("group store down"),
        )

        assert outcome.provider_fields is fields
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
            outcome = self._enrich(ProviderLookup(fields=fields, raw_payload={"companyType": "STARTUP"}))

        assert outcome.provider_fields is fields
        capture_mock.assert_called_once()
        # The live-store write still happened despite the archive failure.
        assert OrganizationEnrichment.objects.filter(organization=self.organization).exists()

    # ---------- fit evaluation ----------

    def test_fit_scores_the_raw_payload_next_to_the_clay_score(self):
        pha_client = MagicMock()
        fields = EnrichmentFields(company_type="STARTUP", headcount=12)
        outcome = self._enrich(
            ProviderLookup(fields=fields, raw_payload=_company()), pha_client=pha_client, domain="acme.ai"
        )

        assert outcome.fit is not None and outcome.fit.score == 100
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_score"] == 100
        assert record.data["icp_fit_version"] == "v0.5"
        assert record.data["icp_fit_status"] == "scored"
        assert record.data["icp_fit_lists_version"] == "test-lists-1"
        assert record.data["icp_fit_components"] == {
            "traction": 35,
            "capital": 30,
            "ai_pilled": 15,
            "headcount_growth": 10,
            "software_relevance": 10,
        }
        # The clay score wrote its own family from the same enrichment, untouched by fit.
        assert record.data["icp_score_version"] == "clay-parity-2"
        properties = pha_client.group_identify.call_args.kwargs["properties"]
        assert properties["icp_fit_score"] == 100
        assert properties["icp_fit_status"] == "scored"

    def test_fit_mirrors_the_person_on_the_first_attempt_without_a_person_read(self):
        # icp_fit_score is a brand-new person key nothing else writes: no ownership guard,
        # no person lookup, mirrored on every attempt — unlike the guarded clay mirror.
        pha_client = MagicMock()
        fields = EnrichmentFields(company_type="STARTUP")
        with (
            patch("products.growth.backend.enrichment.core.read_clay_bridge_inputs", return_value=ClayBridgeInputs()),
            patch("products.growth.backend.enrichment.core.get_person_by_distinct_id") as person_mock,
        ):
            async_to_sync(enrich_organization)(
                organization_id=str(self.organization.id),
                domain="acme.ai",
                provider=_FakeProvider(ProviderLookup(fields=fields, raw_payload=_company())),
                pha_client=pha_client,
                is_recheck=False,
                distinct_id="signer-distinct-id",
            )

        person_mock.assert_not_called()
        pha_client.set.assert_called_once_with(
            distinct_id="signer-distinct-id",
            properties={"icp_fit_score": 100, "icp_fit_version": "v0.5", "icp_fit_status": "scored"},
        )

    def test_student_role_disqualifies_fit_regardless_of_the_payload(self):
        pha_client = MagicMock()
        fields = EnrichmentFields(company_type="STARTUP")
        self._enrich(
            ProviderLookup(fields=fields, raw_payload=_company()),
            role_at_organization="Student",
            pha_client=pha_client,
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_score"] == 0
        assert record.data["icp_fit_status"] == "disqualified"
        assert record.data["icp_fit_dq_reason"] == "role=student"

    def test_fit_insufficient_data_writes_status_only(self):
        pha_client = MagicMock()
        fields = EnrichmentFields(company_type="STARTUP")
        outcome = self._enrich(ProviderLookup(fields=fields, raw_payload=_empty_shell()), pha_client=pha_client)

        assert outcome.fit is not None and outcome.fit.status == "insufficient_data"
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert "icp_fit_score" not in record.data
        assert record.data["icp_fit_status"] == "insufficient_data"
        properties = pha_client.group_identify.call_args.kwargs["properties"]
        assert properties["icp_fit_status"] == "insufficient_data"
        assert "icp_fit_score" not in properties

    def test_fit_miss_scores_from_the_latest_matched_archived_payload(self):
        # First attempt matched and archived; the recheck misses. The fit score must come
        # from the archived payload (EnrichmentFields lack description/tags/series).
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload=_company()
        )
        OrganizationEnrichment.objects.create(organization=self.organization, data={"headcount": 12})
        pha_client = MagicMock()

        outcome = self._enrich(
            ProviderLookup(fields=None, raw_payload=None), is_recheck=True, pha_client=pha_client, domain="acme.ai"
        )

        assert outcome.provider_fields is None  # the workflow's matched signal tracks the lookup
        assert outcome.fit is not None and outcome.fit.score == 100
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_score"] == 100

    def test_fit_sentinel_only_archive_is_not_found(self):
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"companyFound": False}
        )
        outcome = self._enrich(ProviderLookup(fields=None, raw_payload=None))

        assert outcome.fit is not None and outcome.fit.status == "not_found"
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_status"] == "not_found"
        assert "icp_fit_score" not in record.data
        assert "icp_score" not in record.data  # no fields -> no clay score either

    def test_fresh_miss_records_not_found_for_the_reenrichment_sweep(self):
        outcome = self._enrich(ProviderLookup(fields=None, raw_payload=None))

        assert outcome.provider_fields is None
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data == {
            "icp_fit_status": "not_found",
            "icp_fit_version": "v0.5",
            "icp_fit_lists_version": "test-lists-1",
        }

    def test_no_active_lists_degrades_to_clay_and_fields_only(self):
        IcpScoringConfig.objects.update(is_active=False)
        clear_lists_cache()
        pha_client = MagicMock()
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)

        with patch("products.growth.backend.enrichment.core.capture_exception") as capture_mock:
            outcome = self._enrich(
                ProviderLookup(fields=fields, raw_payload=_company()),
                role_at_organization="engineering",
                pha_client=pha_client,
            )

        capture_mock.assert_called_once()
        assert outcome.provider_fields is fields
        assert outcome.fit is None
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12  # clay unaffected by the fit degrade
        assert "icp_fit_status" not in record.data

    def test_no_active_lists_and_a_miss_writes_nothing(self):
        IcpScoringConfig.objects.update(is_active=False)
        clear_lists_cache()
        pha_client = MagicMock()

        outcome = self._enrich(ProviderLookup(fields=None, raw_payload=None), pha_client=pha_client)

        assert outcome.provider_fields is None and outcome.fit is None
        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()
        pha_client.group_identify.assert_not_called()

    def test_fit_scoring_failure_degrades_to_clay_and_fields_only(self):
        fields = EnrichmentFields(headcount=750, country="US", founded_year=2021)
        with (
            patch(
                "products.growth.backend.enrichment.core.score_company",
                side_effect=RuntimeError("scorer exploded"),
            ),
            patch("products.growth.backend.enrichment.core.capture_exception") as capture_mock,
        ):
            outcome = self._enrich(
                ProviderLookup(fields=fields, raw_payload=_company()), role_at_organization="engineering"
            )

        capture_mock.assert_called_once()
        assert outcome.provider_fields is fields
        assert outcome.fit is None
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_score"] == 12
        assert "icp_fit_score" not in record.data

    def test_scoreless_fit_mirrors_status_only(self):
        pha_client = MagicMock()
        fields = EnrichmentFields(company_type="STARTUP")
        self._enrich(
            ProviderLookup(fields=fields, raw_payload=_empty_shell()),
            pha_client=pha_client,
            distinct_id="signer-distinct-id",
        )

        pha_client.set.assert_called_once_with(
            distinct_id="signer-distinct-id", properties={"icp_fit_status": "insufficient_data"}
        )
