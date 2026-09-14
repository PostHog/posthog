from typing import Optional

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from asgiref.sync import async_to_sync

from products.growth.backend.enrichment.bridge import ClayBridgeInputs, OrganizationBridgeInputs, WizardBridgeInputs
from products.growth.backend.enrichment.context import EnrichmentContext, EnrichmentPhase
from products.growth.backend.enrichment.core import enrich_organization
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.icp_lists import clear_lists_cache
from products.growth.backend.enrichment.providers import EnrichmentProvider, ProviderLookup
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch


class _FakeProvider(EnrichmentProvider):
    name = "harmonic"

    def __init__(self, lookup: ProviderLookup, *, status: Optional[str] = None):
        self._lookup = lookup
        self._status = status

    async def enrich_by_domain(self, domain: str) -> ProviderLookup:
        return self._lookup

    async def enrichment_status_for(self, urn: str) -> Optional[str]:
        return self._status


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


class TestEnrichmentCorePhases(BaseTest):
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

    def _run(
        self,
        *,
        provider,
        pha_client,
        is_recheck,
        role_at_organization,
        geoip_country_code,
        distinct_id,
        domain,
        bridge_inputs,
        person,
    ):
        ctx = EnrichmentContext(
            organization_id=str(self.organization.id),
            domain=domain,
            phase=EnrichmentPhase.RECHECK if is_recheck else EnrichmentPhase.AT_SIGNUP,
            distinct_id=distinct_id,
            role_at_organization=role_at_organization,
            geoip_country_code=geoip_country_code,
        )
        with (
            patch(
                "products.growth.backend.enrichment.core.read_organization_bridge_inputs",
                return_value=bridge_inputs,
            ),
            patch("products.growth.backend.enrichment.core.get_person_by_distinct_id", return_value=person),
        ):
            return async_to_sync(enrich_organization)(ctx, provider=provider, pha_client=pha_client)

    def _rows(self):
        return list(
            OrganizationEnrichmentFetch.objects.filter(organization=self.organization)
            .order_by("id")
            .values_list("provider", "is_recheck", "payload")
        )

    def test_at_signup_match(self):
        pha_client = MagicMock()
        provider = _FakeProvider(
            ProviderLookup(
                fields=EnrichmentFields(
                    company_type="STARTUP", headcount=12, founded_year=2020, ownership_status="PRIVATE"
                ),
                raw_payload=_company(),
                enrichment_urn="urn:harmonic:1",
            )
        )

        outcome = self._run(
            provider=provider,
            pha_client=pha_client,
            is_recheck=False,
            role_at_organization="engineering",
            geoip_country_code="US",
            distinct_id="d1",
            domain="acme.com",
            bridge_inputs=OrganizationBridgeInputs(
                clay=ClayBridgeInputs(est_revenue=None), wizard=WizardBridgeInputs()
            ),
            person=None,
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        self.assertEqual(
            record.data,
            {
                "company_type": "STARTUP",
                "headcount": 12,
                "founded_year": 2020,
                "ownership_status": "PRIVATE",
                "country": "US",
                "icp_score": 12,
                "icp_score_version": "clay-parity-2",
                "icp_fit_status": "scored",
                "icp_fit_version": "v0.6",
                "icp_fit_lists_version": "test-lists-1",
                "icp_fit_score": 100,
                "icp_fit_components": {
                    "traction": 35,
                    "capital": 30,
                    "ai_pilled": 15,
                    "headcount_growth": 10,
                    "software_relevance": 10,
                },
                "icp_fit_flags": {
                    "quality_investor": True,
                    "data_coverage": 4,
                    "low_confidence": False,
                    "agency_flag": False,
                    "nonprofit_flag": False,
                    "wizard_ai_sdk": False,
                    "ai_pilled_source": "harmonic",
                },
            },
        )
        self.assertEqual(self._rows(), [("harmonic", False, {**_company(), "enrichmentUrn": "urn:harmonic:1"})])
        self.assertEqual(
            pha_client.group_identify.call_args_list,
            [
                call(
                    "organization",
                    str(self.organization.id),
                    properties={
                        "enrichment_company_type": "STARTUP",
                        "icp_employees": 12,
                        "icp_country": "US",
                        "enrichment_founded_year": 2020,
                        "enrichment_ownership_status": "PRIVATE",
                        "icp_score": 12,
                        "icp_score_version": "clay-parity-2",
                        "icp_fit_score": 100,
                        "icp_fit_version": "v0.6",
                        "icp_fit_status": "scored",
                    },
                )
            ],
        )
        self.assertEqual(
            pha_client.set.call_args_list,
            [
                call(
                    distinct_id="d1",
                    properties={"icp_fit_score": 100, "icp_fit_version": "v0.6", "icp_fit_status": "scored"},
                )
            ],
        )
        self.assertEqual(
            outcome.provider_fields,
            EnrichmentFields(company_type="STARTUP", headcount=12, founded_year=2020, ownership_status="PRIVATE"),
        )
        self.assertEqual(outcome.fit.status, "scored")
        self.assertEqual(outcome.fit.score, 100)
        self.assertEqual(outcome.enrichment_status, None)

    def test_recheck_miss_scores_from_archive(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={
                "work_email": True,
                "signup_role": "engineering",
                "company_type": "STARTUP",
                "headcount": 12,
                "founded_year": 2020,
                "ownership_status": "PRIVATE",
                "country": "US",
            },
        )
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            is_recheck=False,
            payload={**_company(), "enrichmentUrn": "urn:harmonic:1"},
        )
        pha_client = MagicMock()
        provider = _FakeProvider(ProviderLookup(fields=None, raw_payload=None, enrichment_urn=None), status="COMPLETED")
        person = MagicMock()
        person.properties = {"icp_score": 7, "icp_score_version": "clay-parity-2"}

        outcome = self._run(
            provider=provider,
            pha_client=pha_client,
            is_recheck=True,
            role_at_organization="engineering",
            geoip_country_code=None,
            distinct_id="d1",
            domain="acme.com",
            bridge_inputs=OrganizationBridgeInputs(
                clay=ClayBridgeInputs(est_revenue=None), wizard=WizardBridgeInputs(ai_sdk_detected=True)
            ),
            person=person,
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        self.assertEqual(
            record.data,
            {
                "work_email": True,
                "signup_role": "engineering",
                "company_type": "STARTUP",
                "headcount": 12,
                "founded_year": 2020,
                "ownership_status": "PRIVATE",
                "country": "US",
                "icp_score": 12,
                "icp_score_version": "clay-parity-2",
                "icp_fit_status": "scored",
                "icp_fit_version": "v0.6",
                "icp_fit_lists_version": "test-lists-1",
                "icp_fit_score": 100,
                "icp_fit_components": {
                    "traction": 35,
                    "capital": 30,
                    "ai_pilled": 15,
                    "headcount_growth": 10,
                    "software_relevance": 10,
                },
                "icp_fit_flags": {
                    "quality_investor": True,
                    "data_coverage": 4,
                    "low_confidence": False,
                    "agency_flag": False,
                    "nonprofit_flag": False,
                    "wizard_ai_sdk": True,
                    "ai_pilled_source": "both",
                },
            },
        )
        self.assertEqual(
            self._rows(),
            [
                ("harmonic", False, {**_company(), "enrichmentUrn": "urn:harmonic:1"}),
                ("harmonic", True, {"companyFound": False, "enrichmentUrn": None, "enrichmentStatus": "COMPLETED"}),
            ],
        )
        self.assertEqual(
            pha_client.group_identify.call_args_list,
            [
                call(
                    "organization",
                    str(self.organization.id),
                    properties={
                        "enrichment_company_type": "STARTUP",
                        "icp_employees": 12,
                        "icp_country": "US",
                        "enrichment_founded_year": 2020,
                        "enrichment_ownership_status": "PRIVATE",
                        "icp_score": 12,
                        "icp_score_version": "clay-parity-2",
                        "icp_fit_score": 100,
                        "icp_fit_version": "v0.6",
                        "icp_fit_status": "scored",
                    },
                )
            ],
        )
        self.assertEqual(
            pha_client.set.call_args_list,
            [
                call(distinct_id="d1", properties={"icp_score": 12, "icp_score_version": "clay-parity-2"}),
                call(
                    distinct_id="d1",
                    properties={"icp_fit_score": 100, "icp_fit_version": "v0.6", "icp_fit_status": "scored"},
                ),
            ],
        )
        self.assertEqual(outcome.provider_fields, None)
        self.assertEqual(outcome.fit.status, "scored")
        self.assertEqual(outcome.fit.score, 100)
        self.assertEqual(outcome.enrichment_status, "COMPLETED")

    def test_recheck_match_with_stored_country(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization, data={"work_email": True, "country": "DE"}
        )
        pha_client = MagicMock()
        provider = _FakeProvider(
            ProviderLookup(
                fields=EnrichmentFields(company_type="STARTUP", headcount=40),
                raw_payload=_company(headcount=40),
                enrichment_urn=None,
            ),
            status=None,
        )

        outcome = self._run(
            provider=provider,
            pha_client=pha_client,
            is_recheck=True,
            role_at_organization=None,
            geoip_country_code=None,
            distinct_id="d2",
            domain="acme.com",
            bridge_inputs=OrganizationBridgeInputs(),
            person=None,
        )

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        self.assertEqual(
            record.data,
            {
                "work_email": True,
                "country": "DE",
                "company_type": "STARTUP",
                "headcount": 40,
                "icp_score": 0,
                "icp_score_version": "clay-parity-2",
                "icp_fit_status": "scored",
                "icp_fit_version": "v0.6",
                "icp_fit_lists_version": "test-lists-1",
                "icp_fit_score": 100,
                "icp_fit_components": {
                    "traction": 35,
                    "capital": 30,
                    "ai_pilled": 15,
                    "headcount_growth": 10,
                    "software_relevance": 10,
                },
                "icp_fit_flags": {
                    "quality_investor": True,
                    "data_coverage": 4,
                    "low_confidence": False,
                    "agency_flag": False,
                    "nonprofit_flag": False,
                    "wizard_ai_sdk": False,
                    "ai_pilled_source": "harmonic",
                },
            },
        )
        self.assertEqual(
            self._rows(),
            [("harmonic", True, {**_company(headcount=40), "enrichmentUrn": None, "enrichmentStatus": None})],
        )
        self.assertEqual(
            pha_client.group_identify.call_args_list,
            [
                call(
                    "organization",
                    str(self.organization.id),
                    properties={
                        "enrichment_company_type": "STARTUP",
                        "icp_employees": 40,
                        "icp_country": "DE",
                        "icp_score": 0,
                        "icp_score_version": "clay-parity-2",
                        "icp_fit_score": 100,
                        "icp_fit_version": "v0.6",
                        "icp_fit_status": "scored",
                    },
                )
            ],
        )
        self.assertEqual(
            pha_client.set.call_args_list,
            [
                call(distinct_id="d2", properties={"icp_score": 0, "icp_score_version": "clay-parity-2"}),
                call(
                    distinct_id="d2",
                    properties={"icp_fit_score": 100, "icp_fit_version": "v0.6", "icp_fit_status": "scored"},
                ),
            ],
        )
        self.assertEqual(outcome.provider_fields, EnrichmentFields(company_type="STARTUP", headcount=40))
        self.assertEqual(outcome.fit.status, "scored")
        self.assertEqual(outcome.fit.score, 100)
        self.assertEqual(outcome.enrichment_status, None)
