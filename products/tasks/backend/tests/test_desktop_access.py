from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Team

from products.tasks.backend.access import (
    DESKTOP_ACCESS_GATE_FLAG,
    DesktopAccessReason,
    DesktopAccessResolutionError,
    get_desktop_access_decision,
    has_tasks_access,
)
from products.tasks.backend.logic.services.code_usage_gate import code_access_required_response
from products.tasks.backend.models import CodeInvite, CodeInviteRedemption

from ee.billing.billing_manager import OrganizationFundingStatus, PrepaidCreditState, StartupProgramLabel


class TestDesktopAccessPolicy(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.feature_flag_patcher = patch("products.tasks.backend.access.get_feature_flag_or_none")
        self.mock_feature_flag = self.feature_flag_patcher.start()

        def feature_flag_value(flag_key: str, *_args: object, **_kwargs: object) -> bool:
            return flag_key == DESKTOP_ACCESS_GATE_FLAG

        self.mock_feature_flag.side_effect = feature_flag_value

    def tearDown(self) -> None:
        self.feature_flag_patcher.stop()
        super().tearDown()

    @parameterized.expand(
        [
            ("normal", None, PrepaidCreditState.NONE, True, None),
            (
                "startup",
                "Startup",
                PrepaidCreditState.NONE,
                False,
                DesktopAccessReason.STARTUP_PLAN,
            ),
            ("yc", "YC", PrepaidCreditState.NONE, False, DesktopAccessReason.STARTUP_PLAN),
            ("pending", None, PrepaidCreditState.PENDING, False, DesktopAccessReason.PREPAID_CREDITS),
            ("active", None, PrepaidCreditState.ACTIVE, False, DesktopAccessReason.PREPAID_CREDITS),
            ("exhausted", None, PrepaidCreditState.EXHAUSTED, True, None),
            ("expired", None, PrepaidCreditState.EXPIRED, True, None),
            (
                "combined",
                "Startup",
                PrepaidCreditState.ACTIVE,
                False,
                DesktopAccessReason.STARTUP_PLAN,
            ),
        ]
    )
    @patch("products.tasks.backend.access._get_funding_status")
    def test_policy_matrix(
        self,
        _name: str,
        startup_program_label: StartupProgramLabel | None,
        prepaid_credit_state: PrepaidCreditState,
        expected_allowed: bool,
        expected_reason: DesktopAccessReason | None,
        mock_funding,
    ) -> None:
        mock_funding.return_value = OrganizationFundingStatus(
            startup_program_label=startup_program_label,
            prepaid_credit_state=prepaid_credit_state,
        )

        decision = get_desktop_access_decision(self.user, self.organization)

        self.assertEqual(decision.allowed, expected_allowed)
        self.assertEqual(decision.reason, expected_reason)

    @patch("products.tasks.backend.access._get_funding_status")
    @patch("products.tasks.backend.access.feature_enabled_or_false", return_value=True)
    def test_rollout_flag_off_preserves_legacy_feature_flag_access(self, _mock_legacy_flag, mock_funding) -> None:
        self.mock_feature_flag.side_effect = [False]

        decision = get_desktop_access_decision(self.user, self.organization)

        self.assertTrue(decision.allowed)
        self.assertEqual(self.mock_feature_flag.call_count, 1)
        mock_funding.assert_not_called()

    @patch("products.tasks.backend.access._get_funding_status")
    @patch("products.tasks.backend.access.feature_enabled_or_false", return_value=False)
    def test_rollout_flag_off_preserves_legacy_invite_access(self, _mock_legacy_flag, mock_funding) -> None:
        invite = CodeInvite.objects.create(code="LEGACYCODE", max_redemptions=1, is_active=True)
        CodeInviteRedemption.objects.create(invite_code=invite, user=self.user)
        self.mock_feature_flag.side_effect = [False]

        decision = get_desktop_access_decision(self.user, self.organization)

        self.assertTrue(decision.allowed)
        mock_funding.assert_not_called()

    @patch("products.tasks.backend.access._get_funding_status")
    @patch("products.tasks.backend.access.feature_enabled_or_false", return_value=False)
    def test_rollout_flag_off_preserves_legacy_denial(self, _mock_legacy_flag, mock_funding) -> None:
        self.mock_feature_flag.side_effect = [False]

        decision = get_desktop_access_decision(self.user, self.organization)

        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.reason)
        mock_funding.assert_not_called()

    @patch("products.tasks.backend.access._get_funding_status")
    def test_indeterminate_rollout_flag_fails_closed(self, mock_funding) -> None:
        self.mock_feature_flag.side_effect = [None]

        with self.assertRaises(DesktopAccessResolutionError):
            get_desktop_access_decision(self.user, self.organization)

        self.assertEqual(self.mock_feature_flag.call_count, 1)
        mock_funding.assert_not_called()

    @patch("products.tasks.backend.access._get_funding_status")
    def test_override_grants_access_before_funding_resolution(self, mock_funding) -> None:
        self.mock_feature_flag.side_effect = [True, True]

        decision = get_desktop_access_decision(self.user, self.organization)

        self.assertTrue(decision.allowed)
        mock_funding.assert_not_called()

    @patch(
        "products.tasks.backend.logic.services.code_usage_gate.get_desktop_access_decision",
        side_effect=DesktopAccessResolutionError("unavailable"),
    )
    @patch("products.tasks.backend.logic.services.code_usage_gate.get_authenticator_scopes", return_value=[])
    def test_compute_gate_fails_closed_on_resolution_error(self, _mock_scopes, _mock_decision) -> None:
        response = code_access_required_response(MagicMock(), self.organization)

        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["code"], "desktop_access_unavailable")

    @patch("products.tasks.backend.access._get_funding_status")
    def test_access_code_does_not_affect_authorization_after_rollout(self, mock_funding) -> None:
        invite = CodeInvite.objects.create(code="ACCESSCODE", max_redemptions=1, is_active=True)
        CodeInviteRedemption.objects.create(invite_code=invite, user=self.user)
        mock_funding.return_value = OrganizationFundingStatus(
            startup_program_label="Startup",
            prepaid_credit_state=PrepaidCreditState.NONE,
        )

        decision = get_desktop_access_decision(self.user, self.organization)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, DesktopAccessReason.STARTUP_PLAN)

    @parameterized.expand([(None,), ("control",), ("false",)])
    def test_indeterminate_feature_flag_fails_closed(self, flag_value) -> None:
        self.mock_feature_flag.side_effect = [True, flag_value]

        with self.assertRaises(DesktopAccessResolutionError):
            get_desktop_access_decision(self.user, self.organization)

    @patch(
        "products.tasks.backend.access._get_funding_status",
        side_effect=DesktopAccessResolutionError("unavailable"),
    )
    def test_funding_failure_fails_closed(self, _mock_funding) -> None:
        with self.assertRaises(DesktopAccessResolutionError):
            get_desktop_access_decision(self.user, self.organization)

    @patch("products.tasks.backend.access._get_funding_status")
    def test_project_endpoint_is_scoped_to_each_organization(self, mock_funding) -> None:
        other_organization = Organization.objects.create(name="Other organization")
        other_team = Team.objects.create(organization=other_organization, name="Other project")
        OrganizationMembership.objects.create(
            organization=other_organization,
            user=self.user,
            level=OrganizationMembership.Level.MEMBER,
        )

        def funding_status(_user, organization: Organization) -> OrganizationFundingStatus:
            if organization.id == self.organization.id:
                return OrganizationFundingStatus(
                    startup_program_label=None,
                    prepaid_credit_state=PrepaidCreditState.NONE,
                )
            return OrganizationFundingStatus(
                startup_program_label="YC",
                prepaid_credit_state=PrepaidCreditState.NONE,
            )

        mock_funding.side_effect = funding_status

        allowed_response = self.client.get(f"/api/projects/{self.team.id}/desktop/access/")
        blocked_response = self.client.get(f"/api/projects/{other_team.id}/desktop/access/")

        self.assertEqual(allowed_response.status_code, status.HTTP_200_OK)
        self.assertEqual(allowed_response.json(), {"allowed": True, "reason": None})
        self.assertEqual(blocked_response.status_code, status.HTTP_200_OK)
        self.assertEqual(blocked_response.json(), {"allowed": False, "reason": "startup_plan"})

    @patch("products.tasks.backend.presentation.views.api.tasks_access.has_loops_access", return_value=True)
    @patch("products.tasks.backend.access.feature_enabled_or_false", return_value=True)
    def test_legacy_endpoint_preserves_feature_flag_access(self, _mock_legacy_flag, _mock_loops) -> None:
        response = self.client.get("/api/code/invites/check-access/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"has_access": True, "has_loops_access": True})

    @patch("products.tasks.backend.presentation.views.api.tasks_access.has_loops_access", return_value=False)
    @patch("products.tasks.backend.access.feature_enabled_or_false", return_value=False)
    def test_legacy_endpoint_preserves_invite_access(self, _mock_legacy_flag, _mock_loops) -> None:
        invite = CodeInvite.objects.create(code="ENDPOINTCODE", max_redemptions=1, is_active=True)
        CodeInviteRedemption.objects.create(invite_code=invite, user=self.user)

        response = self.client.get("/api/code/invites/check-access/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"has_access": True, "has_loops_access": False})

    @patch("products.tasks.backend.presentation.views.api.tasks_access.has_loops_access", return_value=False)
    @patch("products.tasks.backend.access.feature_enabled_or_false", return_value=False)
    def test_legacy_endpoint_preserves_denial(self, _mock_legacy_flag, _mock_loops) -> None:
        response = self.client.get("/api/code/invites/check-access/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"has_access": False, "has_loops_access": False})

    @patch(
        "products.tasks.backend.presentation.views.desktop_access.get_desktop_access_decision",
        side_effect=DesktopAccessResolutionError,
    )
    def test_project_endpoint_returns_retryable_service_error(self, _mock_decision) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/desktop/access/")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["code"], "desktop_access_unavailable")


class TestTasksAccessFlags(BaseTest):
    @parameterized.expand(
        [
            ("desktop_waitlist", {"tasks"}, True),
            ("posthog_ai_composer", {"phai-sandbox-mode"}, True),
            ("neither", set(), False),
        ]
    )
    def test_either_access_flag_grants_access(self, _name: str, enabled_flags: set[str], expected: bool) -> None:
        with patch(
            "products.tasks.backend.access.feature_enabled_or_false",
            side_effect=lambda flag_key, *_args, **_kwargs: flag_key in enabled_flags,
        ):
            assert has_tasks_access(self.user) is expected
