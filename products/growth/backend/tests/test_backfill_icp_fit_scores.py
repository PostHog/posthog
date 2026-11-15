from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.enrichment.bridge import OrganizationBridgeInputs, WizardBridgeInputs
from products.growth.backend.enrichment.fit_score import score_company
from products.growth.backend.enrichment.icp_lists import build_curated_lists, clear_lists_cache
from products.growth.backend.enrichment.writer import write_organization_enrichment
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch

_COMMAND_MODULE = "products.growth.backend.management.commands.backfill_icp_fit_scores"
_GATES_MODULE = "products.growth.backend.enrichment.gates"

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
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
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
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
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

    def test_writes_the_backfill_evaluation_kind(self):
        record = self._record({})

        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_regional_ph_client", return_value=MagicMock()),
            patch(f"{_COMMAND_MODULE}.read_organization_bridge_inputs", return_value=OrganizationBridgeInputs()),
        ):
            call_command("backfill_icp_fit_scores", "--delay=0")

        record.refresh_from_db()
        assert record.data["icp_fit_evaluation_kind"] == "backfill"
        assert record.data["icp_fit_evaluated_at"]

    def _member_org_record(self, email: str, data: dict) -> tuple[User, OrganizationEnrichment]:
        organization = Organization.objects.create(name=email)
        user = User.objects.create_user(email=email, password=None, first_name="signup")
        OrganizationMembership.objects.create(organization=organization, user=user)
        OrganizationEnrichmentFetch.objects.create(organization=organization, provider="harmonic", payload=_PAYLOAD)
        return user, OrganizationEnrichment.objects.create(organization=organization, data=data)

    def _backfill(self, pha_client: MagicMock) -> None:
        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_regional_ph_client", return_value=pha_client),
            patch(f"{_COMMAND_MODULE}.read_organization_bridge_inputs", return_value=OrganizationBridgeInputs()),
        ):
            call_command("backfill_icp_fit_scores", "--delay=0")

    @parameterized.expand(
        [
            (
                "stored_signup_domain",
                "founder@stripe.com",
                {"icp_fit_signup": {"role": "", "domain": "proton.me", "wizard_ai_sdk": True}},
            ),
            ("member_email_without_a_stored_domain", "founder@proton.me", {"icp_fit_flags": {"wizard_ai_sdk": True}}),
        ]
    )
    def test_clears_the_fit_of_an_org_scored_with_a_personal_email_domain(self, _name, email, saved):
        IcpScoringConfig.objects.filter(is_active=True).update(
            scoring_rules={"source": "return {'status': 'disqualified', 'score': 0, 'dq_reason': 'any'};"}
        )
        clear_lists_cache()
        user, record = self._member_org_record(
            email, {"icp_fit_status": "scored", "icp_fit_score": 75, "icp_fit_version": "v0.7", **saved}
        )
        pha_client = MagicMock()

        self._backfill(pha_client)

        record.refresh_from_db()
        assert record.data["icp_fit_status"] == "not_found"
        assert "icp_fit_score" not in record.data
        assert record.data["work_email"] is False
        assert record.data["icp_fit_signup"] == {"role": "", "domain": "proton.me", "wizard_ai_sdk": True}
        assert pha_client.group_identify.call_args.kwargs["properties"] == {"icp_fit_status": "not_found"}
        pha_client.set.assert_called_once_with(distinct_id=user.distinct_id, properties={"icp_fit_status": "not_found"})

    def test_keeps_scoring_with_the_stored_domain_after_the_member_switches_to_a_personal_email(self):
        _, record = self._member_org_record(
            "founder@gmail.com",
            {"icp_fit_status": "scored", "icp_fit_score": 75, "icp_fit_signup": {"domain": "stripe.com"}},
        )
        pha_client = MagicMock()

        self._backfill(pha_client)

        record.refresh_from_db()
        assert record.data["icp_fit_signup"]["domain"] == "stripe.com"
        assert "work_email" not in record.data
        pha_client.set.assert_not_called()

    def test_policy_change_stops_an_old_backfill_before_it_overwrites_a_new_score(self):
        record = self._record({})
        next_config = IcpScoringConfig.objects.create(
            version="test-lists-2",
            scoring_rules={"source": "return {'status': 'scored', 'score': 0, 'components': {}};"},
        )
        old_client, current_client = MagicMock(), MagicMock()

        def activate_and_score_new_policy(**kwargs):
            with patch("products.growth.backend.models.clear_lists_cache"):
                next_config.activate()
            fit = score_company(_PAYLOAD, lists=build_curated_lists(next_config), wizard_ai_sdk=True)
            write_organization_enrichment(
                organization_id=str(self.organization.id),
                fields=None,
                pha_client=current_client,
                fit=fit,
                fit_evaluation_kind="backfill",
            )
            return OrganizationBridgeInputs(wizard=WizardBridgeInputs(ai_sdk_detected=True))

        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.get_regional_ph_client", return_value=old_client),
            patch(f"{_COMMAND_MODULE}.read_organization_bridge_inputs", side_effect=activate_and_score_new_policy),
        ):
            with self.assertRaisesRegex(CommandError, "scoring configuration changed"):
                call_command("backfill_icp_fit_scores", delay=0)

        record.refresh_from_db()
        assert record.data["icp_fit_lists_version"] == next_config.version
        assert record.data["icp_fit_score"] == 0
        assert current_client.group_identify.call_args.kwargs["properties"]["icp_fit_score"] == 0
        old_client.group_identify.assert_not_called()
