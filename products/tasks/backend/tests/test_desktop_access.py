from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Team

from products.tasks.backend.access import DesktopAccessReason, DesktopAccessResolutionError, get_desktop_access_decision
from products.tasks.backend.logic.services.code_usage_gate import code_access_required_response

from ee.billing.billing_manager import OrganizationFundingStatus, PrepaidCreditState, StartupProgramLabel


class TestDesktopAccessPolicy(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.feature_flag_patcher = patch("products.tasks.backend.access.get_feature_flag_or_none")
        self.mock_feature_flag = self.feature_flag_patcher.start()

        def feature_flag_value(*_args: object, **_kwargs: object) -> bool:
            return False

        self.mock_feature_flag.side_effect = feature_flag_value

    def tearDown(self) -> None:
        self.feature_flag_patcher.stop()
        super().tearDown()

    @override_settings(DEBUG=True)
    @patch("products.tasks.backend.access._get_funding_status")
    def test_debug_mode_allows_access_without_external_resolution(self, mock_funding) -> None:
        decision = get_desktop_access_decision(self.user, self.organization)

        self.assertTrue(decision.allowed)
        self.mock_feature_flag.assert_not_called()
        mock_funding.assert_not_called()

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
    def test_override_grants_access_before_funding_resolution(self, mock_funding) -> None:
        self.mock_feature_flag.side_effect = [True]

        decision = get_desktop_access_decision(self.user, self.organization)

        self.assertTrue(decision.allowed)
        mock_funding.assert_not_called()

    @parameterized.expand(
        [
            ("allowed", None, PrepaidCreditState.NONE, True),
            ("startup", "Startup", PrepaidCreditState.NONE, False),
            ("prepaid", None, PrepaidCreditState.ACTIVE, False),
        ]
    )
    @patch("products.tasks.backend.access._get_funding_status")
    def test_funding_cache_reuses_the_decision_within_its_window(
        self, _name, startup_program_label, prepaid_credit_state, expected_allowed, mock_funding
    ) -> None:
        mock_funding.return_value = OrganizationFundingStatus(
            startup_program_label=startup_program_label, prepaid_credit_state=prepaid_credit_state
        )
        first = get_desktop_access_decision(self.user, self.organization, funding_cache_seconds=300)
        second = get_desktop_access_decision(self.user, self.organization, funding_cache_seconds=300)

        self.assertEqual((first.allowed, second.allowed), (expected_allowed, expected_allowed))
        self.assertEqual(first, second)
        self.assertEqual(mock_funding.call_count, 1)
        # The per-user override flag is never cached.
        self.assertEqual(self.mock_feature_flag.call_count, 2)

    @patch("products.tasks.backend.access._get_funding_status")
    def test_funding_cache_lives_for_the_window_it_was_given(self, mock_funding) -> None:
        mock_funding.return_value = OrganizationFundingStatus(
            startup_program_label=None, prepaid_credit_state=PrepaidCreditState.NONE
        )
        with patch("products.tasks.backend.access.cache.set", wraps=cache.set) as cache_set:
            get_desktop_access_decision(self.user, self.organization, funding_cache_seconds=300)
        cache_set.assert_called_once_with(
            f"desktop_access_funding_decision:{self.organization.id}", "allowed", timeout=300
        )

    @patch("products.tasks.backend.access._get_funding_status")
    def test_without_a_funding_cache_every_call_reads_funding(self, mock_funding) -> None:
        mock_funding.return_value = OrganizationFundingStatus(
            startup_program_label=None, prepaid_credit_state=PrepaidCreditState.NONE
        )
        get_desktop_access_decision(self.user, self.organization)
        get_desktop_access_decision(self.user, self.organization)
        self.assertEqual(mock_funding.call_count, 2)

    @patch("products.tasks.backend.access._get_funding_status")
    def test_a_funding_failure_is_not_cached(self, mock_funding) -> None:
        mock_funding.side_effect = [
            DesktopAccessResolutionError("unavailable"),
            OrganizationFundingStatus(startup_program_label=None, prepaid_credit_state=PrepaidCreditState.NONE),
        ]
        with self.assertRaises(DesktopAccessResolutionError):
            get_desktop_access_decision(self.user, self.organization, funding_cache_seconds=300)
        self.assertTrue(get_desktop_access_decision(self.user, self.organization, funding_cache_seconds=300).allowed)
        self.assertEqual(mock_funding.call_count, 2)

    @patch("products.tasks.backend.access._get_funding_status")
    def test_an_unexpected_cached_value_falls_through_to_the_live_lookup(self, mock_funding) -> None:
        mock_funding.return_value = OrganizationFundingStatus(
            startup_program_label="Startup", prepaid_credit_state=PrepaidCreditState.NONE
        )
        for unexpected in (["allowed"], "not_a_decision"):
            cache.set(f"desktop_access_funding_decision:{self.organization.id}", unexpected, timeout=300)
            decision = get_desktop_access_decision(self.user, self.organization, funding_cache_seconds=300)
            self.assertFalse(decision.allowed)
        self.assertEqual(mock_funding.call_count, 2)

    @patch("products.tasks.backend.access._get_funding_status")
    def test_a_cache_error_falls_through_to_the_live_lookup(self, mock_funding) -> None:
        mock_funding.return_value = OrganizationFundingStatus(
            startup_program_label="Startup", prepaid_credit_state=PrepaidCreditState.NONE
        )
        with (
            patch("products.tasks.backend.access.cache.get", side_effect=ConnectionError("down")),
            patch("products.tasks.backend.access.cache.set", side_effect=ConnectionError("down")),
        ):
            decision = get_desktop_access_decision(self.user, self.organization, funding_cache_seconds=300)
        self.assertFalse(decision.allowed)
        mock_funding.assert_called_once()

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

    @parameterized.expand([(None,), ("control",), ("false",)])
    def test_indeterminate_override_flag_fails_closed(self, flag_value) -> None:
        self.mock_feature_flag.side_effect = [flag_value]

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

    @parameterized.expand(
        [
            ("allowed", None, True),
            ("startup", "Startup", False),
        ]
    )
    @patch("products.tasks.backend.presentation.views.api.tasks_access.has_loops_access", return_value=True)
    @patch("products.tasks.backend.access._get_funding_status")
    def test_legacy_endpoint_uses_access_policy(
        self,
        _name: str,
        startup_program_label: StartupProgramLabel | None,
        expected_access: bool,
        mock_funding,
        _mock_loops,
    ) -> None:
        mock_funding.return_value = OrganizationFundingStatus(
            startup_program_label=startup_program_label,
            prepaid_credit_state=PrepaidCreditState.NONE,
        )

        response = self.client.get("/api/code/invites/check-access/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"has_access": expected_access, "has_loops_access": True})

    @patch(
        "products.tasks.backend.presentation.views.desktop_access.get_desktop_access_decision",
        side_effect=DesktopAccessResolutionError,
    )
    def test_project_endpoint_returns_retryable_service_error(self, _mock_decision) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/desktop/access/")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["code"], "desktop_access_unavailable")
