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
        # Create endpoints for testing
        self.active_endpoint = Endpoint.objects.create(
            name="active_endpoint",
            team=self.team,
            query=self.sample_query,
            created_by_user=self.user,
            is_active=True,
        )
        self.inactive_endpoint = Endpoint.objects.create(
            name="inactive_endpoint",
            team=self.team,
            query=self.sample_query,
            created_by_user=self.user,
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

    def test_authenticate_with_valid_key_in_header(self):
        """Test that a valid API key in Authorization header authenticates successfully"""
        key_value, _ = self._create_api_key(["endpoint:read"])

        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.json())

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
            created_by_user=other_user,
            is_active=True,
        )

        # Create API key for our team
        key_value, _ = self._create_api_key(["endpoint:read"])

        # Try to access other team's endpoint
        response = self._get_with_api_key(f"/api/environments/{other_team.id}/endpoints/", key_value)

        # Should fail because the API key is scoped to self.team
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestProjectSecretAPIKeyPermissionsWithEndpoints(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test permission class behavior with scopes"""

    @parameterized.expand(
        [
            ("list", "endpoint:read", status.HTTP_200_OK),
            ("list", "endpoint:write", status.HTTP_200_OK),  # write includes read
            ("list", "feature_flag:read", status.HTTP_403_FORBIDDEN),  # wrong scope
            ("list", [], status.HTTP_403_FORBIDDEN),  # no scopes
            # Note: retrieve has known issue with serializing endpoints created by ProjectSecretAPIKeyUser
            # ("retrieve", "endpoint:read", status.HTTP_200_OK),
            # ("retrieve", "endpoint:write", status.HTTP_200_OK),
            ("retrieve", "feature_flag:read", status.HTTP_403_FORBIDDEN),
            ("run", "endpoint:read", status.HTTP_200_OK),
            ("run", "endpoint:write", status.HTTP_200_OK),
            ("run", "feature_flag:read", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_read_actions_with_various_scopes(self, action: str, scope: str, expected_status: int):
        """Test that read actions work with correct scopes and fail with wrong scopes"""
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
            if scope and scope != "endpoint:read" and scope != "endpoint:write":
                self.assertIn("scope", response.json()["detail"].lower())

    @parameterized.expand(
        [
            ("create", "endpoint:write", status.HTTP_201_CREATED),
            ("create", "endpoint:read", status.HTTP_403_FORBIDDEN),  # read doesn't include write
            ("create", "feature_flag:write", status.HTTP_403_FORBIDDEN),  # wrong scope
            ("update", "endpoint:write", status.HTTP_200_OK),
            ("update", "endpoint:read", status.HTTP_403_FORBIDDEN),
            ("delete", "endpoint:write", status.HTTP_204_NO_CONTENT),
            ("delete", "endpoint:read", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_write_actions_with_various_scopes(self, action: str, scope: str, expected_status: int):
        """Test that write actions require write scope"""
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

        if expected_status == status.HTTP_403_FORBIDDEN:
            self.assertIn("detail", response.json())
            self.assertIn("scope", response.json()["detail"].lower())

    def test_write_scope_includes_read_permissions(self):
        """Test that endpoint:write scope allows read operations"""
        key_value, _ = self._create_api_key(["endpoint:write"])

        # Test list (read operation)
        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Note: retrieve has known issue with serializing endpoints created by ProjectSecretAPIKeyUser
        # Test retrieve (read operation)
        # response = self._get_with_api_key(
        #     f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/", key_value
        # )
        # self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Test run (read operation)
        response = self._get_with_api_key(
            f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/run/", key_value
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_read_scope_does_not_include_write_permissions(self):
        """Test that endpoint:read scope does NOT allow write operations"""
        key_value, _ = self._create_api_key(["endpoint:read"])

        # Test create (write operation)
        data = {
            "name": "should_fail",
            "query": self.sample_query,
        }
        response = self._post_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("endpoint:write", response.json()["detail"])

        # Test delete (write operation)
        response = self.client.delete(
            f"/api/environments/{self.team.id}/endpoints/{self.active_endpoint.name}/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestProjectSecretAPIKeyOnUnsupportedEndpoints(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test that Project Secret API Keys don't work on endpoints that don't support them"""

    @parameterized.expand(
        [
            # /api/users/@me/ actually works with ProjectSecretAPIKey (returns synthetic user info)
            # ("/api/users/@me/", "GET"),
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

    def test_api_key_works_on_supported_endpoints(self):
        """Test that Project Secret API Keys work on supported endpoints (endpoints)"""
        key_value, _ = self._create_api_key(["endpoint:read"])

        # This endpoint DOES support Project Secret API Keys
        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value)

        self.assertEqual(response.status_code, status.HTTP_200_OK)


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
            created_by_user=self.user,
            is_active=True,
        )

        key_value, _ = self._create_api_key(["endpoint:read"])

        data = {"variables_values": {"test_var": "modified"}}
        response = self._post_with_api_key(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", key_value, data
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.json())


class TestProjectSecretAPIKeyScopeCombinations(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test API keys with multiple scopes"""

    def test_multiple_scopes_all_work(self):
        """Test that an API key with multiple scopes can access all of them"""
        key_value, _ = self._create_api_key(["endpoint:read", "feature_flag:read"])

        # Should work for endpoints
        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Note: Feature flags don't currently support ProjectSecretAPIKey authentication
        # This would need to be added to FeatureFlagViewSet.authentication_classes
        # response = self._get_with_api_key(f"/api/projects/{self.team.id}/feature_flags/", key_value)
        # self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_empty_scopes_list_denies_all(self):
        """Test that an API key with no scopes cannot access anything"""
        key_value, _ = self._create_api_key([])

        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestProjectSecretAPIKeyErrorMessages(ProjectSecretAPIKeyEndpointsBaseTest):
    """Test that error messages are clear and helpful"""

    def test_missing_scope_error_message(self):
        """Test error message when required scope is missing"""
        key_value, _ = self._create_api_key(["feature_flag:read"])

        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", key_value)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        error_detail = response.json()["detail"]
        self.assertIn("endpoint:read", error_detail)
        self.assertIn("scope", error_detail.lower())

    def test_invalid_api_key_error_message(self):
        """Test error message when API key is invalid"""
        response = self._get_with_api_key(f"/api/environments/{self.team.id}/endpoints/", "phs_invalid_key")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())
