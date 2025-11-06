import json
from uuid import uuid4

from unittest.mock import MagicMock, _patch, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team
from posthog.models.user import User

from products.enterprise.backend.api.vercel.test.base import VercelTestBase


class TestVercelResourceAPI(VercelTestBase):
    client_id_patcher: _patch
    jwks_patcher: _patch
    mock_get_jwks: MagicMock

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.client_id_patcher = patch(
            "products.enterprise.backend.settings.VERCEL_CLIENT_INTEGRATION_ID", "test_audience"
        )
        cls.jwks_patcher = patch("products.enterprise.backend.api.authentication.get_vercel_jwks")
        cls.client_id_patcher.start()
        cls.mock_get_jwks = cls.jwks_patcher.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_id_patcher.stop()
        cls.jwks_patcher.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.mock_get_jwks.return_value = self.mock_jwks

        self.primary_resource = self.create_resource()

    def create_installation(self, installation_id=None, email=None):
        installation_id = installation_id or f"icfg_{uuid4().hex[:24]}"
        email = email or f"test-{uuid4().hex[:8]}@example.com"

        user = User.objects.create_user(email=email, password="test", first_name="Test")
        org = Organization.objects.create(name=f"Org {uuid4().hex[:8]}")
        user.join(organization=org)
        team = Team.objects.create(organization=org, name=f"Team {uuid4().hex[:8]}")

        integration = OrganizationIntegration.objects.create(
            organization=org,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=installation_id,
            config={"billing_plan_id": "free"},
            created_by=user,
        )

        return {"id": installation_id, "user": user, "org": org, "team": team, "integration": integration}

    def create_resource(self, installation=None):
        if installation is None:
            team = self.team
            user = self.user
            installation_id = self.installation_id
        else:
            team = installation["team"]
            user = installation["user"]
            installation_id = installation["id"]

        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config={"productId": "posthog", "name": "Test Resource", "billingPlanId": "free", "metadata": {}},
            created_by=user,
        )

        return {
            "resource": resource,
            "resource_id": str(resource.pk),
            "installation_id": installation_id,
            "base_url": f"/api/vercel/v1/installations/{installation_id}/resources",
            "resource_url": f"/api/vercel/v1/installations/{installation_id}/resources/{resource.pk}/",
        }

    def request(self, method, url, data=None, auth_for=None):
        auth_for = auth_for or self.installation_id
        headers = self.auth_headers(auth_for)

        kwargs: dict[str, str] = {}
        if data:
            kwargs.update(content_type="application/json", data=json.dumps(data))

        return getattr(self.client, method)(url, **headers, **kwargs)

    def auth_headers(self, installation_id, auth_type="user"):
        if auth_type == "user":
            token = self._create_jwt_token(self._create_user_auth_payload(installation_id=installation_id))
        else:  # system
            token = self._create_jwt_token(self._create_system_auth_payload(installation_id=installation_id))

        return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_VERCEL_AUTH": auth_type}

    def assert_success(self, response, expected_status=status.HTTP_200_OK):
        self.assertEqual(response.status_code, expected_status)

    def assert_permission_denied(self, response):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_msg = response.json()["error"]["message"]
        self.assertIn("Resource does not belong to this installation", error_msg)

    def assert_not_found(self, response):
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def assert_bad_request(self, response, error_substring=None):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        if error_substring:
            error_msg = response.json()["error"]["message"]
            self.assertIn(error_substring, error_msg)

    @patch("products.enterprise.backend.vercel.integration.VercelIntegration.create_resource")
    def test_create_resource(self, mock_create):
        mock_create.return_value = {
            "id": "new_resource",
            "productId": "posthog",
            "name": "New Resource",
            "metadata": {},
            "status": "ready",
        }

        data = {"productId": "posthog", "name": "New Resource", "billingPlanId": "free", "metadata": {}}
        url = f"{self.primary_resource['base_url']}/"

        response = self.request("post", url, data)

        self.assert_success(response)
        mock_create.assert_called_once_with(self.installation_id, data)

    @patch("products.enterprise.backend.vercel.integration.VercelIntegration.get_resource")
    def test_get_resource(self, mock_get):
        mock_get.return_value = {
            "id": self.primary_resource["resource_id"],
            "productId": "posthog",
            "name": "Test Resource",
            "metadata": {},
            "status": "ready",
        }

        headers = self.auth_headers(self.installation_id, "system")
        response = self.client.get(self.primary_resource["resource_url"], **headers)

        self.assert_success(response)
        mock_get.assert_called_once_with(self.primary_resource["resource_id"])

    @patch("products.enterprise.backend.vercel.integration.VercelIntegration.update_resource")
    def test_update_resource(self, mock_update):
        mock_update.return_value = {
            "id": self.primary_resource["resource_id"],
            "productId": "posthog",
            "name": "Updated Resource",
            "metadata": {},
            "status": "ready",
        }

        data = {"name": "Updated Resource", "metadata": {}}
        response = self.request("patch", self.primary_resource["resource_url"], data)

        self.assert_success(response)
        mock_update.assert_called_once_with(self.primary_resource["resource_id"], data)

    @patch("products.enterprise.backend.vercel.integration.VercelIntegration.delete_resource")
    def test_delete_resource(self, mock_delete):
        response = self.request("delete", self.primary_resource["resource_url"])

        self.assert_success(response, status.HTTP_204_NO_CONTENT)
        mock_delete.assert_called_once_with(self.primary_resource["resource_id"])

    @parameterized.expand(
        [
            ("get", "system"),
            ("patch", "user"),
            ("delete", "user"),
        ]
    )
    def test_cross_installation_access_denied(self, method, auth_type):
        other_installation = self.create_installation()
        other_resource = self.create_resource(other_installation)

        url = f"{self.primary_resource['base_url']}/{other_resource['resource_id']}/"
        headers = self.auth_headers(self.installation_id, auth_type)

        data = json.dumps({"name": "hacked", "metadata": {}}) if method == "patch" else None
        kwargs = {"content_type": "application/json", "data": data} if data else {}

        response = getattr(self.client, method)(url, **headers, **kwargs)
        self.assert_permission_denied(response)

    @parameterized.expand(
        [
            ("get", "system"),
            ("patch", "user"),
            ("delete", "user"),
        ]
    )
    def test_wrong_installation_context_denied(self, method, auth_type):
        other_installation = self.create_installation()

        url = (
            f"/api/vercel/v1/installations/{other_installation['id']}/resources/{self.primary_resource['resource_id']}/"
        )
        headers = self.auth_headers(other_installation["id"], auth_type)

        data = json.dumps({"name": "hacked", "metadata": {}}) if method == "patch" else None
        kwargs = {"content_type": "application/json", "data": data} if data else {}

        response = getattr(self.client, method)(url, **headers, **kwargs)
        self.assert_permission_denied(response)

    def test_nonexistent_resource_not_found(self):
        url = f"{self.primary_resource['base_url']}/99999/"
        headers = self.auth_headers(self.installation_id, "system")

        response = self.client.get(url, **headers)
        self.assert_not_found(response)

    @parameterized.expand(
        [
            ("abc",),
            ("-1",),
            ("0",),
            ("123abc",),
        ]
    )
    def test_invalid_resource_id_rejected(self, invalid_id):
        url = f"{self.primary_resource['base_url']}/{invalid_id}/"
        headers = self.auth_headers(self.installation_id, "system")

        response = self.client.get(url, **headers)
        self.assert_bad_request(response, "Invalid Resource ID")

    def test_missing_installation_id(self):
        url = "/api/vercel/v1/installations//resources/123/"
        headers = self.auth_headers(self.installation_id, "system")
        response = self.client.get(url, **headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_resource_id(self):
        url = f"{self.primary_resource['base_url']}//"
        headers = self.auth_headers(self.installation_id, "system")
        response = self.client.get(url, **headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("products.enterprise.backend.vercel.integration.VercelIntegration.create_resource")
    def test_integration_errors_bubble_up(self, mock_create):
        from rest_framework.exceptions import ValidationError

        mock_create.side_effect = ValidationError("Something went wrong")

        data = {"productId": "posthog", "name": "Test", "billingPlanId": "free", "metadata": {}}
        url = f"{self.primary_resource['base_url']}/"

        response = self.request("post", url, data)
        self.assert_bad_request(response)

    @patch("products.enterprise.backend.vercel.integration.VercelIntegration.create_resource")
    def test_invalid_resource_config_rejected(self, mock_create):
        mock_create.side_effect = TypeError("ResourceConfig.__init__() missing required positional argument")

        data = {"productId": "posthog"}  # Missing required fields
        url = f"{self.primary_resource['base_url']}/"

        response = self.request("post", url, data)
        self.assert_bad_request(response)
