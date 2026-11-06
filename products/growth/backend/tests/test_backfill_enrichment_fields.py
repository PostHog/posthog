import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization

from products.growth.backend.management.commands.backfill_enrichment_fields import stale_placeholder_keys
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

_COMMAND_MODULE = "products.growth.backend.management.commands.backfill_enrichment_fields"

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


class TestBackfillEnrichmentFields(BaseTest):
    def _fetch(
        self, *, organization=None, payload=_PAYLOAD, fetched_at: dt.datetime | None = None
    ) -> OrganizationEnrichmentFetch:
        organization = organization or self.organization
        fetch = OrganizationEnrichmentFetch.objects.create(
            organization=organization, provider="harmonic", payload=payload
        )
        if fetched_at is not None:
            OrganizationEnrichmentFetch.objects.filter(id=fetch.id).update(fetched_at=fetched_at)
        return fetch

    def test_refuses_outside_us_region(self):
        with patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="EU"):
            with self.assertRaises(CommandError):
                call_command("backfill_enrichment_fields")

    @parameterized.expand([("negative_limit", ["--limit=-1"]), ("negative_delay", ["--delay=-0.5"])])
    def test_refuses_invalid_numeric_options(self, _name, args):
        with patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"):
            with self.assertRaises(CommandError):
                call_command("backfill_enrichment_fields", *args)

    def test_dry_run_writes_nothing(self):
        self._fetch()
        OrganizationEnrichment.objects.create(
            organization=self.organization, data={"funding_stage": "VENTURE_UNKNOWN", "headcount": 5}
        )
        pha_client = MagicMock()
        with (
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=pha_client),
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
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=pha_client),
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
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_enrichment_fields", "--limit=2", "--delay=0")

        assert pha_client.group_identify.call_count == 2

    def test_skips_provider_miss_payload(self):
        self._fetch(payload={"companyFound": False})
        pha_client = MagicMock()

        with (
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=pha_client),
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
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=pha_client),
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
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_client", return_value=pha_client),
        ):
            call_command("backfill_enrichment_fields", "--delay=0")

        pha_client.group_identify.assert_called_once()
        _, kwargs = pha_client.group_identify.call_args
        assert "enrichment_web_traffic" not in kwargs["properties"]
