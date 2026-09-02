from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from parameterized import parameterized

from products.growth.backend.enrichment.bridge import OrganizationBridgeInputs, WizardBridgeInputs
from products.growth.backend.enrichment.icp_lists import clear_lists_cache
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch

_COMMAND_MODULE = "products.growth.backend.management.commands.backfill_icp_fit_scores"

_PAYLOAD = {
    "id": "company-1",
    "company_type": "STARTUP",
    "headcount": 12,
    "funding": {"funding_total": None, "investors": []},
    "tags_v2": [],
    "traction_metrics": {},
}


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
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch(f"{_COMMAND_MODULE}.read_organization_bridge_inputs", **bridge_patch_kwargs),
            patch(f"{_COMMAND_MODULE}.capture_exception") as capture_mock,
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

        with (
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch(
                f"{_COMMAND_MODULE}.read_organization_bridge_inputs",
                side_effect=RuntimeError("group store down"),
            ),
            patch(f"{_COMMAND_MODULE}.capture_exception") as capture_mock,
        ):
            call_command("backfill_icp_fit_scores", "--delay=0")

        capture_mock.assert_called_once()
        record.refresh_from_db()
        assert record.data == {"signup_role": "engineering"}
        pha_client.group_identify.assert_not_called()
