import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, replace_limited_team_tokens

WORKFLOW_QUOTA_RESOURCES = (QuotaResource.WORKFLOW_EMAILS, QuotaResource.WORKFLOW_DESTINATIONS)


def _clear_workflow_quota_limits() -> None:
    for resource in WORKFLOW_QUOTA_RESOURCES:
        replace_limited_team_tokens(resource, {}, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


@time_machine.travel("2026-10-03T12:00:00Z", tick=False)
class TestSendingLimitsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        _clear_workflow_quota_limits()

    def tearDown(self) -> None:
        _clear_workflow_quota_limits()
        super().tearDown()

    def _limit(self, resource: QuotaResource, until_offset_seconds: int = 3600) -> None:
        until = int(timezone.now().timestamp()) + until_offset_seconds
        replace_limited_team_tokens(resource, {self.team.api_token: until}, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)

    def _get(self, emails_sent_last_day: int = 0) -> dict:
        with patch(
            "products.workflows.backend.services.email_sending_allowance.fetch_app_metric_totals_by_team_and_source",
            return_value={self.team.id: {"any": {"email_sent": emails_sent_last_day}}},
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/sending_limits/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def test_nothing_limited_by_default(self) -> None:
        assert self._get() == {
            "email_quota_limited": False,
            "destination_quota_limited": False,
            "email_daily_cap_reached": False,
            "emails_per_day": None,
        }

    @parameterized.expand(
        [
            ("emails", QuotaResource.WORKFLOW_EMAILS, "email_quota_limited"),
            ("destinations", QuotaResource.WORKFLOW_DESTINATIONS, "destination_quota_limited"),
        ]
    )
    def test_reports_the_quota_the_team_is_limited_on(
        self, _name: str, resource: QuotaResource, expected_field: str
    ) -> None:
        self._limit(resource)

        data = self._get()

        assert data[expected_field] is True
        other_field = {"email_quota_limited", "destination_quota_limited"} - {expected_field}
        assert data[other_field.pop()] is False

    def test_an_expired_quota_limit_does_not_count(self) -> None:
        self._limit(QuotaResource.WORKFLOW_EMAILS, until_offset_seconds=-60)

        assert self._get()["email_quota_limited"] is False

    def test_a_different_team_being_limited_does_not_count(self) -> None:
        replace_limited_team_tokens(
            QuotaResource.WORKFLOW_EMAILS,
            {"phc_other_team": int(timezone.now().timestamp()) + 3600},
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
        )

        assert self._get()["email_quota_limited"] is False

    @parameterized.expand(
        [
            ("at_the_cap", "enforce", 100, True),
            ("under_the_cap", "enforce", 99, False),
            ("caps_only_measured", "shadow", 100, False),
        ]
    )
    @override_settings(WORKFLOWS_EMAIL_TIER_DAILY_CAPS=[100, 1000])
    def test_reports_when_the_daily_email_cap_is_reached(
        self, _name: str, mode: str, emails_sent_last_day: int, expected: bool
    ) -> None:
        with override_settings(WORKFLOWS_EMAIL_TIER_MODE=mode):
            data = self._get(emails_sent_last_day=emails_sent_last_day)

        assert data["email_daily_cap_reached"] is expected
        assert data["emails_per_day"] == (100 if mode == "enforce" else None)
