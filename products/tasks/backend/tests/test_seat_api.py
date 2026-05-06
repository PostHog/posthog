from typing import ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase

from rest_framework import status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

MOCK_BILLING_TOKEN = "mock-billing-jwt-token"
MOCK_SEAT = {
    "id": "seat_123",
    "user_distinct_id": "user-abc",
    "product_key": "posthog_code",
    "plan_key": "posthog-code-200-20260301",
    "status": "active",
    "end_reason": None,
    "created_at": "2026-04-01T00:00:00Z",
    "active_until": None,
    "active_from": "2026-04-01T00:00:00Z",
}


def _billing_response(data=None, status_code=200, ok=True):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = ok
    resp.json.return_value = data if data is not None else {}
    return resp


class BaseSeatAPITest(TestCase):
    client: APIClient
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    admin_user: ClassVar[User]
    external_user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")

        cls.admin_user = User.objects.create_user(email="admin@example.com", first_name="Admin", password="password")
        cls.organization.members.add(cls.admin_user)
        OrganizationMembership.objects.filter(user=cls.admin_user, organization=cls.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )

        cls.user = User.objects.create_user(email="member@example.com", first_name="Member", password="password")
        cls.organization.members.add(cls.user)

        cls.external_user = User.objects.create_user(
            email="external@example.com", first_name="External", password="password"
        )

    def setUp(self):
        self.client = APIClient()

    def _auth_as_admin(self):
        self.client.force_authenticate(self.admin_user)

    def _auth_as_member(self):
        self.client.force_authenticate(self.user)


@patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
@patch("products.tasks.backend.seat_api.get_cached_instance_license", return_value=MagicMock())
class TestSeatAPIAdminPermissions(BaseSeatAPITest):
    """Non-admin users should be blocked from list and non-me operations."""

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_list_requires_admin(self, mock_request, _mock_license, _mock_token):
        self._auth_as_member()
        response = self.client.get("/api/seats/?product_key=posthog_code")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_list_allowed_for_admin(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response({"seats": [MOCK_SEAT]})
        self._auth_as_admin()
        response = self.client.get("/api/seats/?product_key=posthog_code")
        assert response.status_code == status.HTTP_200_OK

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_retrieve_other_user_requires_admin(self, mock_request, _mock_license, _mock_token):
        self._auth_as_member()
        response = self.client.get(f"/api/seats/{self.admin_user.distinct_id}/?product_key=posthog_code")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_retrieve_me_allowed_for_member(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response({"seat": MOCK_SEAT})
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code")
        assert response.status_code == status.HTTP_200_OK

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_delete_other_user_requires_admin(self, mock_request, _mock_license, _mock_token):
        self._auth_as_member()
        response = self.client.delete(f"/api/seats/{self.admin_user.distinct_id}/?product_key=posthog_code")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_patch_other_user_requires_admin(self, mock_request, _mock_license, _mock_token):
        self._auth_as_member()
        response = self.client.patch(
            f"/api/seats/{self.admin_user.distinct_id}/",
            {"product_key": "posthog_code", "plan_key": "posthog-code-200-20260301"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_create_without_user_distinct_id_returns_400(self, mock_request, _mock_license, _mock_token):
        self._auth_as_member()
        response = self.client.post(
            "/api/seats/",
            {"product_key": "posthog_code", "plan_key": "posthog-code-free-20260301"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "user_distinct_id is required"

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_create_for_other_user_requires_admin(self, mock_request, _mock_license, _mock_token):
        self._auth_as_member()
        response = self.client.post(
            "/api/seats/",
            {"product_key": "posthog_code", "plan_key": "posthog-code-free-20260301", "user_distinct_id": "other-id"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_create_for_self_allowed_for_member(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response({"seat": MOCK_SEAT})
        self._auth_as_member()
        response = self.client.post(
            "/api/seats/",
            {
                "product_key": "posthog_code",
                "plan_key": "posthog-code-free-20260301",
                "user_distinct_id": str(self.user.distinct_id),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_reactivate_other_user_requires_admin(self, mock_request, _mock_license, _mock_token):
        self._auth_as_member()
        response = self.client.post(f"/api/seats/{self.admin_user.distinct_id}/reactivate/", format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_retrieve_non_org_member_rejected(self, mock_request, _mock_license, _mock_token):
        self._auth_as_admin()
        response = self.client.get(f"/api/seats/{self.external_user.distinct_id}/?product_key=posthog_code")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_patch_non_org_member_rejected(self, mock_request, _mock_license, _mock_token):
        self._auth_as_admin()
        response = self.client.patch(
            f"/api/seats/{self.external_user.distinct_id}/",
            {"product_key": "posthog_code", "plan_key": "posthog-code-200-20260301"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_delete_non_org_member_rejected(self, mock_request, _mock_license, _mock_token):
        self._auth_as_admin()
        response = self.client.delete(f"/api/seats/{self.external_user.distinct_id}/?product_key=posthog_code")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_create_for_non_org_member_rejected(self, mock_request, _mock_license, _mock_token):
        self._auth_as_admin()
        response = self.client.post(
            "/api/seats/",
            {
                "product_key": "posthog_code",
                "plan_key": "posthog-code-free-20260301",
                "user_distinct_id": str(self.external_user.distinct_id),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_reactivate_non_org_member_rejected(self, mock_request, _mock_license, _mock_token):
        self._auth_as_admin()
        response = self.client.post(f"/api/seats/{self.external_user.distinct_id}/reactivate/", format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN


@patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
@patch("products.tasks.backend.seat_api.get_cached_instance_license", return_value=MagicMock())
class TestSeatAPIMeResolution(BaseSeatAPITest):
    """``me`` in the URL should resolve to the authenticated user's distinct_id."""

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_retrieve_me_resolves_distinct_id(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response({"seat": MOCK_SEAT})
        self._auth_as_member()
        self.client.get("/api/seats/me/?product_key=posthog_code")
        _, kwargs = mock_request.call_args
        assert str(self.user.distinct_id) in kwargs["url"]

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_delete_me_resolves_distinct_id(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response(status_code=204)
        self._auth_as_member()
        self.client.delete("/api/seats/me/?product_key=posthog_code")
        _, kwargs = mock_request.call_args
        assert str(self.user.distinct_id) in kwargs["url"]

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_patch_me_resolves_distinct_id(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response({"seat": MOCK_SEAT})
        self._auth_as_member()
        self.client.patch(
            "/api/seats/me/",
            {"product_key": "posthog_code", "plan_key": "posthog-code-200-20260301"},
            format="json",
        )
        _, kwargs = mock_request.call_args
        assert str(self.user.distinct_id) in kwargs["url"]

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_reactivate_me_resolves_distinct_id(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response({"seat": MOCK_SEAT})
        self._auth_as_member()
        self.client.post("/api/seats/me/reactivate/", format="json")
        _, kwargs = mock_request.call_args
        assert str(self.user.distinct_id) in kwargs["url"]


@patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
@patch("products.tasks.backend.seat_api.get_cached_instance_license")
class TestSeatAPIBillingUnavailability(BaseSeatAPITest):
    """Graceful handling when the billing service is unreachable or misconfigured."""

    def test_no_license_returns_400(self, mock_license, _mock_token):
        mock_license.return_value = None
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "No organization or license found"

    @patch("products.tasks.backend.seat_api.requests.request", side_effect=Exception("connection refused"))
    def test_billing_request_exception_returns_502(self, mock_request, mock_license, _mock_token):
        import requests as req

        mock_request.side_effect = req.ConnectionError("connection refused")
        mock_license.return_value = MagicMock()
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_billing_invalid_json_returns_502(self, mock_request, mock_license, _mock_token):
        mock_license.return_value = MagicMock()
        billing_resp = MagicMock()
        billing_resp.status_code = 200
        billing_resp.ok = True
        billing_resp.json.side_effect = ValueError("invalid json")
        mock_request.return_value = billing_resp
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json()["detail"] == "Invalid response from billing service"


@patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
@patch("products.tasks.backend.seat_api.get_cached_instance_license", return_value=MagicMock())
class TestSeatAPIResponseUnwrapping(BaseSeatAPITest):
    """Successful responses with a ``seat`` key are unwrapped; errors pass through."""

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_retrieve_unwraps_seat_envelope(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response({"seat": MOCK_SEAT, "extra": "ignored"})
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == "seat_123"
        assert "extra" not in response.json()

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_list_does_not_unwrap(self, mock_request, _mock_license, _mock_token):
        payload = {"seats": [MOCK_SEAT]}
        mock_request.return_value = _billing_response(payload)
        self._auth_as_admin()
        response = self.client.get("/api/seats/?product_key=posthog_code")
        assert response.status_code == status.HTTP_200_OK
        assert "seats" in response.json()

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_error_response_passes_through(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response({"error": "seat not found"}, status_code=404, ok=False)
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code")
        assert response.status_code == 404
        assert response.json()["error"] == "seat not found"

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_204_returns_no_content(self, mock_request, _mock_license, _mock_token):
        billing_resp = MagicMock()
        billing_resp.status_code = 204
        mock_request.return_value = billing_resp
        self._auth_as_member()
        response = self.client.delete("/api/seats/me/?product_key=posthog_code")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_response_without_seat_key_passes_through(self, mock_request, _mock_license, _mock_token):
        payload = {"message": "ok", "some_data": 123}
        mock_request.return_value = _billing_response(payload)
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload


MOCK_FREE_SEAT = {
    "id": "seat_free",
    "user_distinct_id": "user-abc",
    "product_key": "posthog_code",
    "plan_key": "posthog-code-free-20260301",
    "status": "active",
    "end_reason": None,
    "created_at": "2026-04-01T00:00:00Z",
    "active_until": None,
    "active_from": "2026-04-01T00:00:00Z",
}

MOCK_PRO_SEAT = {
    "id": "seat_pro",
    "user_distinct_id": "user-abc",
    "product_key": "posthog_code",
    "plan_key": "posthog-code-200-20260301",
    "status": "active",
    "end_reason": None,
    "created_at": "2026-04-01T00:00:00Z",
    "active_until": None,
    "active_from": "2026-04-01T00:00:00Z",
}

MOCK_PRO_V2_SEAT = {
    "id": "seat_pro_v2",
    "user_distinct_id": "user-abc",
    "product_key": "posthog_code",
    "plan_key": "posthog-code-pro-200-20260422",
    "status": "active",
    "end_reason": None,
    "created_at": "2026-04-01T00:00:00Z",
    "active_until": None,
    "active_from": "2026-04-01T00:00:00Z",
}


@patch("products.tasks.backend.seat_api.get_cached_instance_license", return_value=MagicMock())
class TestSeatAPIBestPlan(BaseSeatAPITest):
    """``best=true`` returns the highest-tier seat across all orgs."""

    org2: ClassVar[Organization]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org2 = Organization.objects.create(name="Second Org")
        cls.org2.members.add(cls.user)

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_single_org_returns_that_seat(self, _mock_token, mock_request, _mock_license):
        mock_request.return_value = _billing_response({"seat": MOCK_FREE_SEAT})
        self._auth_as_admin()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_key"] == "posthog-code-free-20260301"
        assert response.json()["organization_id"] == str(self.organization.id)
        assert response.json()["organization_name"] == "Test Org"

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_multi_org_returns_pro_over_free(self, _mock_token, mock_request, _mock_license):
        mock_request.side_effect = [
            _billing_response({"seat": MOCK_FREE_SEAT}),
            _billing_response({"seat": MOCK_PRO_SEAT}),
        ]
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_key"] == "posthog-code-200-20260301"
        assert "organization_id" in response.json()

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_multi_org_returns_pro_regardless_of_order(self, _mock_token, mock_request, _mock_license):
        mock_request.side_effect = [
            _billing_response({"seat": MOCK_PRO_SEAT}),
            _billing_response({"seat": MOCK_FREE_SEAT}),
        ]
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_key"] == "posthog-code-200-20260301"

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_all_billing_failures_returns_404(self, _mock_token, mock_request, _mock_license):
        mock_request.return_value = _billing_response({"error": "fail"}, status_code=500, ok=False)
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_partial_failure_returns_best_available(self, _mock_token, mock_request, _mock_license):
        mock_request.side_effect = [
            _billing_response({"error": "fail"}, status_code=500, ok=False),
            _billing_response({"seat": MOCK_PRO_SEAT}),
        ]
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_key"] == "posthog-code-200-20260301"

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_best_ignored_for_non_me_pk(self, _mock_token, mock_request, _mock_license):
        mock_request.return_value = _billing_response({"seat": MOCK_SEAT})
        self._auth_as_admin()
        response = self.client.get(f"/api/seats/{self.user.distinct_id}/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert mock_request.call_count == 1

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_without_best_param_does_single_call(self, _mock_token, mock_request, _mock_license):
        mock_request.return_value = _billing_response({"seat": MOCK_SEAT})
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code")
        assert response.status_code == status.HTTP_200_OK
        assert mock_request.call_count == 1

    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_no_orgs_returns_400(self, _mock_token, _mock_license):
        self.client.force_authenticate(self.external_user)
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_pro_v2_prefix_recognized(self, _mock_token, mock_request, _mock_license):
        mock_request.side_effect = [
            _billing_response({"seat": MOCK_FREE_SEAT}),
            _billing_response({"seat": MOCK_PRO_V2_SEAT}),
        ]
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_key"] == "posthog-code-pro-200-20260422"

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_no_plan_key_loses_to_free(self, _mock_token, mock_request, _mock_license):
        no_plan_seat = {**MOCK_FREE_SEAT, "plan_key": None, "id": "seat_none"}
        mock_request.side_effect = [
            _billing_response({"seat": no_plan_seat}),
            _billing_response({"seat": MOCK_FREE_SEAT}),
        ]
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_key"] == "posthog-code-free-20260301"

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_active_free_beats_canceled_pro(self, _mock_token, mock_request, _mock_license):
        canceled_pro = {**MOCK_PRO_SEAT, "status": "canceled", "id": "seat_canceled_pro"}
        mock_request.side_effect = [
            _billing_response({"seat": canceled_pro}),
            _billing_response({"seat": MOCK_FREE_SEAT}),
        ]
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_key"] == "posthog-code-free-20260301"
        assert response.json()["status"] == "active"

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_future_exception_handled_gracefully(self, _mock_token, mock_request, _mock_license):
        mock_request.side_effect = [
            RuntimeError("connection reset"),
            _billing_response({"seat": MOCK_PRO_SEAT}),
        ]
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_key"] == "posthog-code-200-20260301"

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token")
    def test_partial_header_failure_returns_available_seat(self, mock_token, mock_request, _mock_license):
        mock_token.side_effect = [NotAuthenticated("no member"), MOCK_BILLING_TOKEN]
        mock_request.return_value = _billing_response({"seat": MOCK_FREE_SEAT})
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_key"] == "posthog-code-free-20260301"

    @patch("products.tasks.backend.seat_api.requests.request")
    @patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
    def test_same_tier_picks_oldest_seat(self, _mock_token, mock_request, _mock_license):
        newer_pro = {**MOCK_PRO_SEAT, "id": "seat_newer", "created_at": "2026-06-01T00:00:00Z"}
        older_pro = {**MOCK_PRO_SEAT, "id": "seat_older", "created_at": "2026-03-01T00:00:00Z"}
        mock_request.side_effect = [
            _billing_response({"seat": newer_pro}),
            _billing_response({"seat": older_pro}),
        ]
        self._auth_as_member()
        response = self.client.get("/api/seats/me/?product_key=posthog_code&best=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == "seat_older"


@patch("products.tasks.backend.seat_api.build_billing_token", return_value=MOCK_BILLING_TOKEN)
@patch("products.tasks.backend.seat_api.get_cached_instance_license", return_value=MagicMock())
class TestSeatAPIKeyAccess(BaseSeatAPITest):
    """Personal API keys are allowed so the LLM gateway can resolve seats."""

    @patch("products.tasks.backend.seat_api.requests.request")
    def test_personal_api_key_allowed(self, mock_request, _mock_license, _mock_token):
        mock_request.return_value = _billing_response({"seat": MOCK_SEAT})
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="test",
            user=self.admin_user,
            scopes=["*"],
            secure_value=hash_key_value(token),
        )
        self.client.logout()
        response = self.client.get(
            "/api/seats/me/?product_key=posthog_code",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_200_OK
