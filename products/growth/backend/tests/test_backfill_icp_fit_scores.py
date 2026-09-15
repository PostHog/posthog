import json
import datetime as dt
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from django.core.management import CommandError, call_command
from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization

from products.growth.backend.enrichment.bridge import OrganizationBridgeInputs, WizardBridgeInputs
from products.growth.backend.enrichment.icp_lists import clear_lists_cache
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch

_LOGIC_MODULE = "products.growth.backend.enrichment.fit_backfill"
_GATES_MODULE = "products.growth.backend.enrichment.gates"

_PAYLOAD = {
    "id": "company-1",
    "company_type": "STARTUP",
    "headcount": 12,
    "funding": {"funding_total": None, "investors": []},
    "tags_v2": [],
    "traction_metrics": {},
}

_SCORED_PAYLOAD = {
    "id": "company-2",
    "company_type": "STARTUP",
    "headcount": 12,
    "description": "Developer platform",
    "funding": {"funding_total": 3_000_000, "investors": [{"name": "Y Combinator"}]},
    "tags_v2": [
        {"display_value": "Artificial Intelligence", "type": "MARKET"},
        {"display_value": "Developer Tools", "type": "MARKET"},
    ],
    "traction_metrics": {
        "web_traffic": {"latest_metric_value": 20_000, "90d_ago": {"percent_change": 20.0, "change": 3_300}},
        "headcount": {"latest_metric_value": 12, "180d_ago": {"percent_change": 8.0, "change": 1}},
    },
}
_MISS_PAYLOAD = {"companyFound": False}
_SEEDED_RECORD = {
    "work_email": True,
    "signup_role": "engineering",
    "company_type": "STARTUP",
    "icp_fit_dq_reason": "role=student",
}
_STATS_LINES = (
    "evaluated 2\n"
    "  scored: 1 (50.0%)\n"
    "  not_found: 1 (50.0%)\n"
    "  scored: median 74 | >=40 100.0% | >=50 100.0% | >=60 100.0% | >=70 100.0%\n"
)
_PARITY_CSV_HEADER = "domain,score,status,traction,capital,ai_pilled,headcount_growth,software_relevance\n"


class TestBackfillIcpFitScores(BaseTest):
    def setUp(self):
        super().setUp()
        IcpScoringConfig.objects.create(
            version="test-lists-1",
            tags=[],
            quality_investors=[],
            is_active=True,
        )
        clear_lists_cache()

    def tearDown(self):
        clear_lists_cache()
        super().tearDown()

    def _record(self, data):
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            payload=_PAYLOAD,
        )
        return OrganizationEnrichment.objects.create(
            organization=self.organization,
            data=data,
        )

    @parameterized.expand(
        [
            (
                "live_stamp",
                OrganizationBridgeInputs(wizard=WizardBridgeInputs(ai_sdk_detected=True)),
            ),
            ("group_read_failure", RuntimeError("group store down")),
        ]
    )
    def test_wizard_score_survives_a_backfill(self, _name, bridge_result):
        record = self._record(
            {
                "icp_fit_score": 15,
                "icp_fit_flags": {"wizard_ai_sdk": True, "ai_pilled_source": "wizard"},
                "icp_fit_version": "v0.6",
            }
        )
        pha_client = MagicMock()
        bridge_patch_kwargs = (
            {"side_effect": bridge_result} if isinstance(bridge_result, Exception) else {"return_value": bridge_result}
        )

        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch(f"{_LOGIC_MODULE}.read_organization_bridge_inputs", **bridge_patch_kwargs),
            patch(f"{_LOGIC_MODULE}.capture_exception") as capture_mock,
        ):
            call_command("backfill_icp_fit_scores", "--delay=0")

        if isinstance(bridge_result, Exception):
            capture_mock.assert_called_once()
        else:
            capture_mock.assert_not_called()
        record.refresh_from_db()
        assert record.data["icp_fit_score"] == 15
        assert record.data["icp_fit_flags"]["wizard_ai_sdk"] is True
        assert record.data["icp_fit_flags"]["ai_pilled_source"] == "wizard"

    def test_group_read_failure_skips_a_record_without_persisted_wizard_evidence(self):
        record = self._record({"signup_role": "engineering"})
        pha_client = MagicMock()
        out = StringIO()

        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch(
                f"{_LOGIC_MODULE}.read_organization_bridge_inputs",
                side_effect=RuntimeError("group store down"),
            ),
            patch(f"{_LOGIC_MODULE}.capture_exception") as capture_mock,
        ):
            call_command("backfill_icp_fit_scores", "--delay=0", stdout=out, no_color=True)

        capture_mock.assert_called_once()
        assert out.getvalue() == "considered 1, wrote 0, skipped_org_gone 0, skipped_wizard_unavailable 1\n"
        record.refresh_from_db()
        assert record.data == {"signup_role": "engineering"}
        pha_client.group_identify.assert_not_called()

    def test_writes_the_backfill_evaluation_kind(self):
        record = self._record({})

        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.get_regional_ph_client", return_value=MagicMock()),
            patch(f"{_LOGIC_MODULE}.read_organization_bridge_inputs", return_value=OrganizationBridgeInputs()),
        ):
            call_command("backfill_icp_fit_scores", "--delay=0")

        record.refresh_from_db()
        assert record.data["icp_fit_evaluation_kind"] == "backfill"
        assert record.data["icp_fit_evaluated_at"]


class TestBackfillIcpFitScoresGolden(BaseTest):
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

    def _fetch(self, organization, payload, *, age: dt.timedelta):
        fetch = OrganizationEnrichmentFetch.objects.create(
            organization=organization, provider="harmonic", payload=payload
        )
        OrganizationEnrichmentFetch.objects.filter(id=fetch.id).update(fetched_at=timezone.now() - age)

    def _seed(self) -> Organization:
        self._fetch(self.organization, _SCORED_PAYLOAD, age=dt.timedelta(hours=1))
        OrganizationEnrichment.objects.create(organization=self.organization, data={**_SEEDED_RECORD})
        missed = Organization.objects.create(name="missed")
        self._fetch(missed, _MISS_PAYLOAD, age=dt.timedelta(hours=2))
        return missed

    def _call(self, out: StringIO, *args, region="US", pha_client=None, bridge=None):
        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value=region),
            patch(f"{_LOGIC_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch(
                f"{_LOGIC_MODULE}.read_organization_bridge_inputs",
                return_value=bridge or OrganizationBridgeInputs(),
            ),
        ):
            call_command("backfill_icp_fit_scores", *args, stdout=out, no_color=True)

    def _data_without_evaluated_at(self, organization):
        data = dict(OrganizationEnrichment.objects.get(organization=organization).data)
        self.assertTrue(data.pop("icp_fit_evaluated_at"))
        return data

    def _archive(self):
        return list(
            OrganizationEnrichmentFetch.objects.order_by("-fetched_at").values_list(
                "organization_id", "provider", "is_recheck", "payload"
            )
        )

    def _write_parity_dir(self, root: Path, expected_rows: list[str]) -> None:
        (root / "acme.json").write_text(json.dumps({"_domain": "acme.com", "payload": _SCORED_PAYLOAD}))
        (root / "missing.json").write_text(json.dumps({"_domain": "missing.io", "payload": _MISS_PAYLOAD}))
        (root / "expected.csv").write_text(_PARITY_CSV_HEADER + "".join(expected_rows))

    @parameterized.expand([("summary_only", [], ""), ("with_stats", ["--stats"], _STATS_LINES)])
    def test_writes_fit_keys_for_every_latest_fetch(self, _name, extra_args, stats_lines):
        missed = self._seed()
        pha_client = MagicMock()
        out = StringIO()

        self._call(out, "--delay=0", *extra_args, pha_client=pha_client)

        assert (
            out.getvalue()
            == (
                f"wrote {self.organization.id}: scored score=74\n"
                f"wrote {missed.id}: not_found score=None\n"
                "considered 2, wrote 2, skipped_org_gone 0, skipped_wizard_unavailable 0\n"
            )
            + stats_lines
        )
        assert self._data_without_evaluated_at(self.organization) == {
            "work_email": True,
            "signup_role": "engineering",
            "company_type": "STARTUP",
            "icp_fit_status": "scored",
            "icp_fit_version": "v0.6",
            "icp_fit_lists_version": "test-lists-1",
            "icp_fit_evaluation_kind": "backfill",
            "icp_fit_score": 74,
            "icp_fit_components": {
                "traction": 22,
                "capital": 24,
                "ai_pilled": 15,
                "headcount_growth": 6,
                "software_relevance": 7,
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
        }
        assert self._data_without_evaluated_at(missed) == {
            "icp_fit_status": "not_found",
            "icp_fit_version": "v0.6",
            "icp_fit_lists_version": "test-lists-1",
            "icp_fit_evaluation_kind": "backfill",
        }
        assert self._archive() == [
            (self.organization.id, "harmonic", False, _SCORED_PAYLOAD),
            (missed.id, "harmonic", False, _MISS_PAYLOAD),
        ]
        assert pha_client.group_identify.call_args_list == [
            call(
                "organization",
                str(self.organization.id),
                properties={"icp_fit_score": 74, "icp_fit_version": "v0.6", "icp_fit_status": "scored"},
            ),
            call("organization", str(missed.id), properties={"icp_fit_status": "not_found"}),
        ]
        pha_client.set.assert_not_called()
        pha_client.shutdown.assert_called_once()

    def test_dry_run_reports_without_writing(self):
        missed = self._seed()
        pha_client = MagicMock()
        out = StringIO()

        self._call(out, "--dry-run", pha_client=pha_client)

        assert out.getvalue() == (
            f"would write {self.organization.id}: scored score=74\n"
            f"would write {missed.id}: not_found score=None\n"
            "considered 2, would write 2, skipped_org_gone 0, skipped_wizard_unavailable 0\n"
        )
        assert OrganizationEnrichment.objects.get(organization=self.organization).data == _SEEDED_RECORD
        assert not OrganizationEnrichment.objects.filter(organization=missed).exists()
        assert self._archive() == [
            (self.organization.id, "harmonic", False, _SCORED_PAYLOAD),
            (missed.id, "harmonic", False, _MISS_PAYLOAD),
        ]
        pha_client.group_identify.assert_not_called()
        pha_client.set.assert_not_called()
        pha_client.shutdown.assert_called_once()

    @parameterized.expand(
        [
            (
                "outside_cloud",
                [],
                "DEV",
                True,
                True,
                "Signup enrichment is Cloud-only; refusing to backfill in this region",
            ),
            ("zero_limit", ["--limit=0"], "US", True, True, "--limit must be a positive integer"),
            ("negative_delay", ["--delay=-1"], "US", True, True, "--delay must be >= 0"),
            (
                "no_active_lists",
                [],
                "US",
                False,
                True,
                "No active IcpScoringConfig row. Seed one with sync_icp_scoring_lists --activate "
                "(or pass --tags-csv/--investors-csv).",
            ),
            (
                "tags_csv_alone",
                ["--tags-csv=tags.csv"],
                "US",
                True,
                True,
                "--tags-csv and --investors-csv must be given together",
            ),
            (
                "no_regional_client",
                [],
                "US",
                True,
                False,
                "no PostHog client for this instance's region; refusing to backfill",
            ),
            ("parity_without_payloads", ["--parity"], "US", True, True, "--parity requires --payloads"),
        ]
    )
    def test_refuses_with_exact_message(self, _name, args, region, lists_active, has_client, message):
        self._seed()
        if not lists_active:
            IcpScoringConfig.objects.update(is_active=False)
            clear_lists_cache()
        pha_client = MagicMock() if has_client else None
        out = StringIO()

        with self.assertRaises(CommandError) as raised:
            self._call(out, *args, region=region, pha_client=pha_client)

        assert str(raised.exception) == message
        assert out.getvalue() == ""
        assert OrganizationEnrichment.objects.get(organization=self.organization).data == _SEEDED_RECORD
        if pha_client is not None:
            pha_client.group_identify.assert_not_called()

    def test_parity_reports_each_mismatch_and_fails(self):
        out = StringIO()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_parity_dir(root, ["acme.com,80,scored,30,24,15,6,7\n", "missing.io,,not_found,,,,,\n"])
            with self.assertRaises(CommandError) as raised:
                self._call(out, "--parity", f"--payloads={root}", f"--expected={root / 'expected.csv'}")

        assert str(raised.exception) == "parity failed: 1 mismatches"
        assert out.getvalue() == (
            "MISMATCH acme.com: score want='80' got='74', traction want='30' got='22'\n"
            + _STATS_LINES
            + "compared 2 against expected; mismatches 1\n"
        )
        assert not OrganizationEnrichment.objects.exists()

    def test_parity_passes_with_csv_lists(self):
        IcpScoringConfig.objects.update(is_active=False)
        clear_lists_cache()
        out = StringIO()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_parity_dir(root, ["acme.com,74,scored,22,24,15,6,7\n", "missing.io,,not_found,,,,,\n"])
            (root / "tags.csv").write_text(
                "tag,type,recommendation,reason,note\n"
                "Artificial Intelligence,MARKET,ai_positive,,\n"
                "Developer Tools,MARKET,software_positive,,\n"
            )
            (root / "investors.csv").write_text("investor,aliases,notes\nY Combinator,YC,\n")
            self._call(
                out,
                "--parity",
                f"--payloads={root}",
                f"--expected={root / 'expected.csv'}",
                f"--tags-csv={root / 'tags.csv'}",
                f"--investors-csv={root / 'investors.csv'}",
            )

        assert out.getvalue() == _STATS_LINES + "compared 2 against expected; mismatches 0\nparity passed\n"
        assert not OrganizationEnrichment.objects.exists()
