import datetime as dt
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from django.core.management import CommandError, call_command
from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization

from products.growth.backend.enrichment.fields_backfill import stale_placeholder_keys
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

_LOGIC_MODULE = "products.growth.backend.enrichment.fields_backfill"

_PAYLOAD = {
    "companyType": "STARTUP",
    "tractionMetrics": {"webTraffic": {"latestMetricValue": 551400}},
    "tags": [
        {"type": "TECHNOLOGY", "displayValue": "AWS"},
        {"type": "TECHNOLOGY", "displayValue": "React"},
        {"type": "INDUSTRY", "displayValue": "Enterprise Software", "isPrimaryTag": True},
    ],
    "tagsV2": [],
}

_FUNDED_PAYLOAD = {
    "companyType": "ENTERPRISE",
    "headcount": 250,
    "location": {"country": "Germany"},
    "foundingDate": {"date": "2015-06-01"},
    "funding": {
        "fundingStage": "SERIES_B",
        "fundingTotal": 40_000_000,
        "numFundingRounds": 3,
        "lastFundingTotal": 25_000_000,
        "lastFundingAt": "2025-02-25T00:00:00Z",
        "investors": [{"name": "Y Combinator"}, {"fullName": "Ada Angel"}],
    },
    "tagsV2": [{"displayValue": "Machine Learning", "type": "MARKET"}],
    "ownershipStatus": "PRIVATE",
    "customerType": "B2B",
}
_MISS_PAYLOAD = {"companyFound": False}
_SHELL_PAYLOAD = {"enrichmentUrn": "urn:harmonic:4"}
_SEEDED_RECORD = {"funding_stage": "VENTURE_UNKNOWN", "company_type_deterministic": "startup"}
_SEEDED_KEYS = "['company_type', 'industry', 'is_yc_company', 'web_traffic']"
_FUNDED_KEYS = (
    "['company_type', 'country', 'customer_type', 'founded_year', 'funding_stage', 'headcount', 'industry', "
    "'investors', 'is_ai_native', 'is_yc_company', 'last_round_date', 'last_round_size', 'ownership_status', "
    "'total_raised']"
)


def _create_fetch(organization, payload, fetched_at: dt.datetime | None = None) -> OrganizationEnrichmentFetch:
    fetch = OrganizationEnrichmentFetch.objects.create(organization=organization, provider="harmonic", payload=payload)
    if fetched_at is not None:
        OrganizationEnrichmentFetch.objects.filter(id=fetch.id).update(fetched_at=fetched_at)
    return fetch


class TestBackfillEnrichmentFields(BaseTest):
    def _fetch(
        self, *, organization=None, payload=_PAYLOAD, fetched_at: dt.datetime | None = None
    ) -> OrganizationEnrichmentFetch:
        return _create_fetch(organization or self.organization, payload, fetched_at)

    def test_refuses_outside_us_region(self):
        with patch(f"{_LOGIC_MODULE}.get_instance_region", return_value="EU"):
            with self.assertRaises(CommandError) as raised:
                call_command("backfill_enrichment_fields")

        assert str(raised.exception) == "Signup enrichment is US-only; refusing to backfill in this region"

    @parameterized.expand(
        [
            ("negative_limit", ["--limit=-1"], "--limit must be a positive integer"),
            ("negative_delay", ["--delay=-0.5"], "--delay must be >= 0"),
        ]
    )
    def test_refuses_invalid_numeric_options(self, _name, args, message):
        with patch(f"{_LOGIC_MODULE}.get_instance_region", return_value="US"):
            with self.assertRaises(CommandError) as raised:
                call_command("backfill_enrichment_fields", *args)

        assert str(raised.exception) == message

    def test_dry_run_writes_nothing(self):
        self._fetch()
        OrganizationEnrichment.objects.create(
            organization=self.organization, data={"funding_stage": "VENTURE_UNKNOWN", "headcount": 5}
        )
        pha_client = MagicMock()
        with (
            patch(f"{_LOGIC_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_enrichment_fields", "--dry-run")

        pha_client.group_identify.assert_not_called()
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data == {"funding_stage": "VENTURE_UNKNOWN", "headcount": 5}

    def test_writes_derived_fields_from_the_latest_fetch_per_org(self):
        older_payload = {**_PAYLOAD, "tractionMetrics": {"webTraffic": {"latestMetricValue": 100}}}
        self._fetch(payload=older_payload, fetched_at=timezone.now() - dt.timedelta(days=1))
        self._fetch(payload=_PAYLOAD)
        pha_client = MagicMock()

        with (
            patch(f"{_LOGIC_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_enrichment_fields", "--delay=0")

        pha_client.group_identify.assert_called_once()
        _, kwargs = pha_client.group_identify.call_args
        assert kwargs["properties"]["enrichment_web_traffic"] == 551400

    def test_limit_respected(self):
        for i in range(3):
            org = Organization.objects.create(name=f"org-{i}")
            self._fetch(organization=org)
        pha_client = MagicMock()

        with (
            patch(f"{_LOGIC_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_enrichment_fields", "--limit=2", "--delay=0")

        assert pha_client.group_identify.call_count == 2

    def test_skips_provider_miss_payload(self):
        self._fetch(payload={"companyFound": False})
        pha_client = MagicMock()

        with (
            patch(f"{_LOGIC_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_enrichment_fields", "--delay=0")

        pha_client.group_identify.assert_not_called()

    @parameterized.expand(
        [
            ("placeholder_no_longer_derived", {"funding_stage": "VENTURE_UNKNOWN"}, {}, ["funding_stage"]),
            ("real_value_never_stripped", {"funding_stage": "SEED"}, {}, []),
            (
                "still_derived_kept",
                {"funding_stage": "VENTURE_UNKNOWN"},
                {"funding_stage": "VENTURE_UNKNOWN"},
                [],
            ),
        ]
    )
    def test_stale_placeholder_keys(self, _name, data, derived, expected):
        assert stale_placeholder_keys(data, derived) == expected

    @parameterized.expand(
        [
            ("placeholder_stripped", "VENTURE_UNKNOWN", False),
            ("real_stage_preserved", "SEED", True),
        ]
    )
    def test_command_strips_only_stale_placeholders_from_the_record(self, _name, stored_stage, survives):
        # _PAYLOAD carries no funding data, so the re-derived fields have no funding_stage.
        self._fetch()
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={"funding_stage": stored_stage, "company_type_deterministic": "startup"},
        )
        pha_client = MagicMock()

        with (
            patch(f"{_LOGIC_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_enrichment_fields", "--delay=0")

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert ("funding_stage" in record.data) is survives
        assert record.data["company_type_deterministic"] == "startup"
        assert record.data["web_traffic"] == 551400

    def test_missing_keys_skip_cleanly_without_placeholder_values(self):
        self._fetch(payload={"companyType": "ENTERPRISE"})
        pha_client = MagicMock()

        with (
            patch(f"{_LOGIC_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_enrichment_fields", "--delay=0")

        pha_client.group_identify.assert_called_once()
        _, kwargs = pha_client.group_identify.call_args
        assert "enrichment_web_traffic" not in kwargs["properties"]


class TestBackfillEnrichmentFieldsGolden(BaseTest):
    def _seed(self) -> tuple[Organization, Organization, Organization]:
        now = timezone.now()
        _create_fetch(self.organization, _PAYLOAD, now - dt.timedelta(hours=1))
        OrganizationEnrichment.objects.create(organization=self.organization, data={**_SEEDED_RECORD})
        funded = Organization.objects.create(name="funded")
        _create_fetch(funded, _FUNDED_PAYLOAD, now - dt.timedelta(hours=2))
        missed = Organization.objects.create(name="missed")
        _create_fetch(missed, _MISS_PAYLOAD, now - dt.timedelta(hours=3))
        shell = Organization.objects.create(name="shell")
        _create_fetch(shell, _SHELL_PAYLOAD, now - dt.timedelta(hours=4))
        return funded, missed, shell

    def _call(self, out: StringIO, *args, pha_client: MagicMock) -> None:
        with (
            patch(f"{_LOGIC_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_enrichment_fields", *args, stdout=out, no_color=True)

    def _archive(self):
        return list(
            OrganizationEnrichmentFetch.objects.order_by("-fetched_at").values_list(
                "organization_id", "provider", "is_recheck", "payload"
            )
        )

    def _records(self) -> dict:
        return {record.organization_id: record.data for record in OrganizationEnrichment.objects.all()}

    def _seeded_archive(self, funded, missed, shell):
        return [
            (self.organization.id, "harmonic", False, _PAYLOAD),
            (funded.id, "harmonic", False, _FUNDED_PAYLOAD),
            (missed.id, "harmonic", False, _MISS_PAYLOAD),
            (shell.id, "harmonic", False, _SHELL_PAYLOAD),
        ]

    def test_rewrites_current_fields_for_every_latest_fetch(self):
        funded, missed, shell = self._seed()
        pha_client = MagicMock()
        out = StringIO()

        self._call(out, "--delay=0", pha_client=pha_client)

        assert out.getvalue() == (
            f"wrote {self.organization.id}: {_SEEDED_KEYS}, stripped ['funding_stage']\n"
            f"wrote {funded.id}: {_FUNDED_KEYS}\n"
            f"wrote {shell.id}: ['is_yc_company']\n"
            "considered 4, wrote 3, skipped_no_match 1, skipped_empty 0, stripped_stale 1\n"
        )
        assert self._records() == {
            self.organization.id: {
                "company_type_deterministic": "startup",
                "company_type": "STARTUP",
                "web_traffic": 551400,
                "industry": "Enterprise Software",
                "is_yc_company": False,
            },
            funded.id: {
                "company_type": "ENTERPRISE",
                "headcount": 250,
                "industry": "Machine Learning",
                "country": "DE",
                "founded_year": 2015,
                "funding_stage": "SERIES_B",
                "total_raised": 40_000_000,
                "last_round_size": 25_000_000,
                "last_round_date": "2025-02-25",
                "investors": ["Y Combinator", "Ada Angel"],
                "is_yc_company": True,
                "is_ai_native": True,
                "ownership_status": "PRIVATE",
                "customer_type": "B2B",
            },
            shell.id: {"is_yc_company": False},
        }
        assert self._archive() == self._seeded_archive(funded, missed, shell)
        assert pha_client.group_identify.call_args_list == [
            call(
                "organization",
                str(self.organization.id),
                properties={
                    "enrichment_company_type": "STARTUP",
                    "enrichment_web_traffic": 551400,
                    "enrichment_industry": "Enterprise Software",
                    "enrichment_is_yc_company": False,
                },
            ),
            call(
                "organization",
                str(funded.id),
                properties={
                    "enrichment_company_type": "ENTERPRISE",
                    "icp_employees": 250,
                    "enrichment_industry": "Machine Learning",
                    "icp_country": "DE",
                    "enrichment_founded_year": 2015,
                    "enrichment_funding_stage": "SERIES_B",
                    "enrichment_total_raised": 40_000_000,
                    "enrichment_last_round_size": 25_000_000,
                    "enrichment_last_round_date": "2025-02-25",
                    "enrichment_investors": ["Y Combinator", "Ada Angel"],
                    "enrichment_is_yc_company": True,
                    "enrichment_is_ai_native": True,
                    "enrichment_ownership_status": "PRIVATE",
                    "enrichment_customer_type": "B2B",
                },
            ),
            call("organization", str(shell.id), properties={"enrichment_is_yc_company": False}),
        ]
        pha_client.set.assert_not_called()

    def test_dry_run_reports_without_writing(self):
        funded, missed, shell = self._seed()
        pha_client = MagicMock()
        out = StringIO()

        self._call(out, "--dry-run", pha_client=pha_client)

        assert out.getvalue() == (
            f"would write {self.organization.id}: {_SEEDED_KEYS}, "
            "would strip ['funding_stage']\n"
            f"would write {funded.id}: {_FUNDED_KEYS}\n"
            f"would write {shell.id}: ['is_yc_company']\n"
            "considered 4, would write 3, skipped_no_match 1, skipped_empty 0, stripped_stale 1\n"
        )
        assert self._records() == {self.organization.id: _SEEDED_RECORD}
        assert self._archive() == self._seeded_archive(funded, missed, shell)
        pha_client.group_identify.assert_not_called()
        pha_client.set.assert_not_called()

    def test_limit_stops_after_the_newest_fetches(self):
        funded, missed, shell = self._seed()
        pha_client = MagicMock()
        out = StringIO()

        self._call(out, "--limit=1", "--delay=0", pha_client=pha_client)

        assert out.getvalue() == (
            f"wrote {self.organization.id}: {_SEEDED_KEYS}, stripped ['funding_stage']\n"
            "considered 1, wrote 1, skipped_no_match 0, skipped_empty 0, stripped_stale 1\n"
        )
        assert self._records() == {
            self.organization.id: {
                "company_type_deterministic": "startup",
                "company_type": "STARTUP",
                "web_traffic": 551400,
                "industry": "Enterprise Software",
                "is_yc_company": False,
            },
        }
        assert self._archive() == self._seeded_archive(funded, missed, shell)
        assert pha_client.group_identify.call_args_list == [
            call(
                "organization",
                str(self.organization.id),
                properties={
                    "enrichment_company_type": "STARTUP",
                    "enrichment_web_traffic": 551400,
                    "enrichment_industry": "Enterprise Software",
                    "enrichment_is_yc_company": False,
                },
            ),
        ]
        pha_client.set.assert_not_called()
