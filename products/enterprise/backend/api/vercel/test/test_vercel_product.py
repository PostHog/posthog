from unittest.mock import MagicMock, _patch, patch

from rest_framework import status

from products.enterprise.backend.api.vercel.test.base import VercelTestBase


class TestVercelProductAPI(VercelTestBase):
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
        self.mock_get_jwks.return_value = self.mock_jwks

    def test_get_posthog_plans_with_user_auth(self):
        headers = self._get_auth_headers("user")
        response = self.client.get("/api/vercel/v1/products/posthog/plans/", **headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "plans" in data
        assert len(data["plans"]) == 2

    def test_get_posthog_plans_with_system_auth(self):
        headers = self._get_auth_headers("system")
        response = self.client.get("/api/vercel/v1/products/posthog/plans/", **headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "plans" in data
        assert len(data["plans"]) == 2

    def test_get_invalid_product_plans(self):
        headers = self._get_auth_headers("user")
        response = self.client.get("/api/vercel/v1/products/invalid/plans/", **headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
