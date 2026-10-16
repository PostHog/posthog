import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.workflows.backend.models import HogFlow

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, replace_limited_team_tokens

WORKFLOW_QUOTA_RESOURCES = (QuotaResource.WORKFLOW_EMAILS, QuotaResource.WORKFLOW_DESTINATIONS)


def _clear_workflow_quota_limits() -> None:
    for resource in WORKFLOW_QUOTA_RESOURCES:
        replace_limited_team_tokens(resource, {}, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


@time_machine.travel("2026-10-03T12:00:00Z", tick=False)
class TestSendingLimitsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _clear_workflow_quota_limits()

    def tearDown(self) -> None:
        _clear_workflow_quota_limits()
        super().tearDown()

    def _limit(self, resource: QuotaResource, until_offset_seconds: int = 3600) -> None:
        until = int(timezone.now().timestamp()) + until_offset_seconds
        replace_limited_team_tokens(resource, {self.team.api_token: until}, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)

    def _get(self, headers: dict[str, str] | None = None) -> dict[str, object]:
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/sending_limits/", headers=headers)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def test_nothing_limited_by_default(self) -> None:
        assert self._get() == {"email_quota_limited": False, "destination_quota_limited": False}

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

    def test_a_failing_quota_lookup_reads_as_not_limited(self) -> None:
        with patch(
            "products.workflows.backend.services.sending_limits.get_fresh_team_limited_resources",
            side_effect=ConnectionError("redis unavailable"),
        ):
            assert self._get() == {"email_quota_limited": False, "destination_quota_limited": False}

    def test_a_personal_api_key_with_read_scope_can_read_the_limits(self) -> None:
        key = self.create_personal_api_key_with_scopes(["hog_flow:read"])
        self.client.logout()

        data = self._get(headers={"Authorization": f"Bearer {key}"})

        assert data["email_quota_limited"] is False

    def test_a_member_with_access_to_one_workflow_sees_the_quota(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "obj-only@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        flow = HogFlow.objects.create(team=self.team, name="Granted workflow", trigger={"type": "event"})
        AccessControl.objects.create(team=self.team, resource="hog_flow", resource_id=None, access_level="none")
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=str(flow.id),
            access_level="viewer",
            organization_member=membership,
        )
        self._limit(QuotaResource.WORKFLOW_EMAILS)
        self.client.force_login(member)

        assert self._get()["email_quota_limited"] is True
