import json

from unittest.mock import MagicMock, _patch, patch

from rest_framework import status

from products.enterprise.backend.api.vercel.test.base import VercelTestBase


class TestVercelInstallationAPI(VercelTestBase):
    client_id_patcher: _patch
    jwks_patcher: _patch
    mock_get_jwks: MagicMock

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client_id_patcher = patch("ee.settings.VERCEL_CLIENT_INTEGRATION_ID", "test_audience")
        cls.jwks_patcher = patch("ee.api.authentication.get_vercel_jwks")
        cls.client_id_patcher.start()
        cls.mock_get_jwks = cls.jwks_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.client_id_patcher.stop()
        cls.jwks_patcher.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.url = f"/api/vercel/v1/installations/{self.installation_id}/"
        self.upsert_payload = {
            "scopes": ["read", "write"],
            "acceptedPolicies": {"toc": "2024-02-28T10:00:00Z"},
            "credentials": {"access_token": "token", "token_type": "Bearer"},
            "account": {"name": "Account", "url": "https://example.com", "contact": {"email": "test@example.com"}},
        }
        self.update_payload = {"billingPlanId": "pro200"}
        self.mock_get_jwks.return_value = self.mock_jwks

    def _request(self, method, url=None, data=None, auth_type="user", **kwargs):
        headers = self._get_auth_headers(auth_type)
        url = url or self.url
        if data:
            kwargs.update(content_type="application/json", data=json.dumps(data))
        return getattr(self.client, method)(url, **headers, **kwargs)

    @patch("ee.vercel.integration.VercelIntegration.get_installation_billing_plan")
    def test_retrieve_calls_get_installation_billing_plan(self, mock_get):
        mock_get.return_value = {"billingplan": {"id": "free"}}
        response = self._request("get", auth_type="system")

        assert response.status_code == status.HTTP_200_OK
        mock_get.assert_called_once_with(self.installation_id)

    @patch("ee.vercel.integration.VercelIntegration.get_vercel_plans")
    def test_plans_calls_get_vercel_plans(self, mock_plans):
        mock_plans.return_value = [{"id": "free"}, {"id": "paid"}]
        response = self._request("get", url=f"{self.url}plans/", auth_type="system")

        assert response.status_code == status.HTTP_200_OK
        mock_plans.assert_called_once()

    @patch("ee.vercel.integration.VercelIntegration.update_installation")
    def test_update_calls_upsert_installation(self, mock_update):
        response = self._request("patch", data=self.update_payload)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_update.assert_called_once_with(self.installation_id, "pro200")

    @patch("ee.vercel.integration.VercelIntegration.update_installation")
    def test_partial_update_calls_update_installation(self, mock_update):
        response = self._request("patch", data=self.update_payload)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_update.assert_called_once_with(self.installation_id, "pro200")

    @patch("ee.vercel.integration.VercelIntegration.upsert_installation")
    def test_create_calls_upsert_installation(self, mock_upsert):
        response = self._request("put", data=self.upsert_payload)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert mock_upsert.call_count == 1
        call_args = mock_upsert.call_args[0]
        assert call_args[0] == self.installation_id
        assert call_args[1] == self.upsert_payload
        assert hasattr(call_args[2], "user_id")

    @patch("ee.vercel.integration.VercelIntegration.delete_installation")
    def test_destroy_calls_delete_installation(self, mock_delete):
        mock_delete.return_value = {"finalized": True}
        response = self._request("delete")

        assert response.status_code == status.HTTP_200_OK
        mock_delete.assert_called_once_with(self.installation_id)

    def test_invalid_installation_id_format(self):
        url = "/api/vercel/v1/installations/invalid-id/"
        response = self._request("get", url=url, auth_type="system")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
