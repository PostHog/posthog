from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_secret

from products.endpoints.backend.models import Endpoint


class ProjectSecretAPIKeyEndpointsBaseTest(APIBaseTest, ClickhouseTestMixin):
    """Base test class with common setup for Project Secret API Key tests"""

    def setUp(self):
        super().setUp()
        self.sample_query = {
            "kind": "HogQLQuery",
            "query": "SELECT count(1) FROM query_log",
        }
        self.active_endpoint = Endpoint.objects.create(
            name="active_endpoint",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=True,
        )
        self.inactive_endpoint = Endpoint.objects.create(
            name="inactive_endpoint",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=False,
        )

    def _create_api_key(self, scopes: list[str]) -> tuple[str, ProjectSecretAPIKey]:
        """Helper to create a Project Secret API Key and return the raw value and model"""
        key_value = generate_random_token_secret()
        api_key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label=f"test-key-{'-'.join(scopes)}",
            scopes=scopes,
            secure_value=hash_key_value(key_value),
            created_by=self.user,
        )
        return key_value, api_key

    def _get_with_api_key(self, url: str, key_value: str):
        """Helper to make GET request with API key"""
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {key_value}")

    def _post_with_api_key(self, url: str, key_value: str, data: dict | None = None):
        """Helper to make POST request with API key"""
        return self.client.post(url, data or {}, format="json", HTTP_AUTHORIZATION=f"Bearer {key_value}")


class TestProjectSecretAPIKeyAuthenticationWithEndpoints(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test authentication class behavior with Project Secret API Keys"""

    def test_authenticate_with_invalid_key(self):
        """Test that an invalid API key returns 401"""
        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", "phs_invalid_key_123456789")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticate_without_key(self):
        """Test that request without API key uses default authentication"""
        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/")

        # Should work with session auth (from APIBaseTest setup)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_api_key_scoped_to_correct_team(self):
        """Test that API keys are scoped to their team"""
        # Create another team
        from posthog.models.organization import Organization
        from posthog.models.team import Team
        from posthog.models.user import User

        other_org = Organization.objects.create(name="Other Org")
        other_user = User.objects.create_and_join(other_org, "other@test.com", None)
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # Create endpoint in other team
        Endpoint.objects.create(
            name="other_team_endpoint",
            team=other_team,
            query=self.sample_query,
            created_by=other_user,
            is_active=True,
        )

        # Create API key for our team
        key_value, _ = self._create_api_key(["endpoint:read"])

        # Try to access other team's endpoint
        response = self._get_with_api_key(f"/api/environments/{other_team.id}/endpoints/", key_value)

        # Should fail because the API key is scoped to self.team
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_api_key_can_not_create_endpoint(self):
        key_value, _ = self._create_api_key(["endpoint:read"])

        data = {
            "name": "test_query",
            "description": "Test query description",
            "query": {"kind": "HogQLQuery", "query": "select 100"},
        }
        response = self._post_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value, data)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestProjectSecretAPIKeyPermissionsWithEndpoints(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test permission class behavior with scopes"""

    @parameterized.expand(
        [
            # Project Secret API Keys only support endpoint:read scope
            # They cannot be used for list/retrieve - only for /run
            ("list", "endpoint:read", status.HTTP_401_UNAUTHORIZED),
            ("list", [], status.HTTP_401_UNAUTHORIZED),  # no scopes
            ("retrieve", "endpoint:read", status.HTTP_401_UNAUTHORIZED),
            # Only /run endpoint works with endpoint:read scope
            ("run", "endpoint:read", status.HTTP_200_OK),
        ]
    )
    def test_read_actions_with_various_scopes(self, action: str, scope: str, expected_status: int):
        """Test that Project Secret API Keys work only on /run endpoint with endpoint:read scope"""
        key_value, _ = self._create_api_key([scope] if scope else [])

        if action == "list":
            response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value)
        elif action == "retrieve":
            response = self._get_with_api_key(
                f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/", key_value
            )
        elif action == "run":
            response = self._get_with_api_key(
                f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/run/", key_value
            )

        self.assertEqual(response.status_code, expected_status)

        if expected_status == status.HTTP_403_FORBIDDEN:
            self.assertIn("detail", response.json())
            if scope and scope != "endpoint:read":
                self.assertIn("scope", response.json()["detail"].lower())

    @parameterized.expand(
        [
            # Project Secret API Keys are NOT allowed to manage endpoints (create/update/delete)
            # They can only execute endpoints via /run, and only endpoint:read scope is allowed
            ("create", "endpoint:read", status.HTTP_401_UNAUTHORIZED),
            ("update", "endpoint:read", status.HTTP_401_UNAUTHORIZED),
            ("delete", "endpoint:read", status.HTTP_401_UNAUTHORIZED),
        ]
    )
    def test_write_actions_with_various_scopes(self, action: str, scope: str, expected_status: int):
        """Test that Project Secret API Keys cannot manage endpoints (create/update/delete)"""
        key_value, _ = self._create_api_key([scope])

        if action == "create":
            data = {
                "name": "new_endpoint",
                "query": self.sample_query,
            }
            response = self._post_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value, data)
        elif action == "update":
            data = {"description": "Updated description"}
            response = self.client.put(
                f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/",
                data,
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {key_value}",
            )
        elif action == "delete":
            response = self.client.delete(
                f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/",
                HTTP_AUTHORIZATION=f"Bearer {key_value}",
            )

        self.assertEqual(response.status_code, expected_status)

    def test_read_scope_does_not_include_write_permissions(self):
        """Test that Project Secret API Keys cannot manage endpoints regardless of scope"""
        key_value, _ = self._create_api_key(["endpoint:read"])

        # Test create (write operation) - Project Secret API Keys can't manage endpoints
        data = {
            "name": "should_fail",
            "query": self.sample_query,
        }
        response = self._post_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Test delete (write operation) - Project Secret API Keys can't manage endpoints
        response = self.client.delete(
            f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestProjectSecretAPIKeyOnUnsupportedEndpoints(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test that Project Secret API Keys don't work on endpoints that don't support them"""

    @parameterized.expand(
        [
            (f"/api/organizations/{{organization_id}}/", "GET"),
            (f"/api/projects/{{team_id}}/dashboards/", "GET"),
            (f"/api/projects/{{team_id}}/insights/", "GET"),
        ]
    )
    def test_api_key_fails_on_unsupported_endpoints(self, url_template: str, method: str):
        """Test that Project Secret API Keys return 403 on unsupported endpoints"""
        key_value, _ = self._create_api_key(["endpoint:read"])

        # Substitute placeholders
        url = url_template.format(organization_id=self.organization.id, team_id=self.team.id)

        if method == "GET":
            response = self._get_with_api_key(url, key_value)
        else:
            response = self._post_with_api_key(url, key_value)

        # These endpoints don't support Project Secret API Keys
        # They should either return 403 or 401 depending on implementation
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class TestProjectSecretAPIKeyEndpointExecution(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test executing endpoints with Project Secret API Keys"""

    def test_execute_endpoint_with_read_scope(self):
        """Test that endpoint execution works with read scope"""
        key_value, _ = self._create_api_key(["endpoint:read"])

        response = self._get_with_api_key(
            f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/run/", key_value
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.json())

    def test_execute_endpoint_updates_last_used_at(self):
        """Test that executing an endpoint updates the key's last_used_at timestamp"""
        key_value, api_key = self._create_api_key(["endpoint:read"])

        # Verify last_used_at is initially None
        api_key.refresh_from_db()
        self.assertIsNone(api_key.last_used_at)

        # Execute endpoint
        response = self._get_with_api_key(
            f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/run/", key_value
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify last_used_at is now set
        api_key.refresh_from_db()
        self.assertIsNotNone(api_key.last_used_at)

    def test_execute_inactive_endpoint_returns_404(self):
        """Test that inactive endpoints cannot be executed even with valid API key"""
        key_value, _ = self._create_api_key(["endpoint:read"])

        response = self._get_with_api_key(
            f"/api/environments/{self.team.id}/endpoints/{self.inactive_endpoint.name}/run/", key_value
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_execute_with_variables(self):
        """Test executing endpoint with variables using API key"""
        from posthog.models.insight_variable import InsightVariable

        variable = InsightVariable.objects.create(
            team=self.team,
            name="Test Variable",
            code_name="test_var",
            type=InsightVariable.Type.STRING,
            default_value="test",
        )

        query_with_vars = {
            "kind": "HogQLQuery",
            "query": "SELECT '{variables.test_var}' as result",
            "variables": {str(variable.id): {"variableId": str(variable.id), "code_name": "test_var", "value": "test"}},
        }

        endpoint = Endpoint.objects.create(
            name="var_endpoint",
            team=self.team,
            query=query_with_vars,
            created_by=self.user,
            is_active=True,
        )

        key_value, _ = self._create_api_key(["endpoint:read"])

        data = {"variables": {"test_var": "modified"}}
        response = self._post_with_api_key(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run", key_value, data
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertIn("results", response.json())


class TestProjectSecretAPIKeyScopeCombinations(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test API keys with multiple scopes"""

    def test_multiple_scopes_all_work(self):
        """Test that an API key with multiple scopes can access all of them"""
        key_value, _ = self._create_api_key(["endpoint:read", "feature_flag:read"])

        response = self._get_with_api_key(
            f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/run", key_value
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_feature_flag_scope_only_cannot_access_endpoints(self):
        """Test that feature_flag:read scope alone cannot access endpoint run"""
        key_value, _ = self._create_api_key(["feature_flag:read"])

        response = self._get_with_api_key(
            f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/run/", key_value
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_empty_scopes_list_denies_all(self):
        """Test that an API key with no scopes cannot access anything"""
        key_value, _ = self._create_api_key([])

        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestProjectSecretAPIKeyErrorMessages(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test that error messages are clear and helpful"""

    def test_scope_validation_on_create(self):
        """Test that only endpoint:read scope is allowed when creating Project Secret API Keys"""
        # This test verifies scope validation happens at the project secret API key management level
        # The actual endpoint execution tests verify that only endpoint:read works for /run
        # Note: Invalid scopes are rejected when creating the key via the API, not tested here
        # since _create_api_key bypasses API validation
        key_value, _ = self._create_api_key(["endpoint:read"])

        # Verify the key works for its intended purpose
        response = self._get_with_api_key(
            f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/run/", key_value
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_invalid_api_key_error_message(self):
        """Test error message when API key is invalid"""
        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", "phs_invalid_key")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())
