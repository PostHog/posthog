from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from products.endpoints.backend.tests.conftest import create_endpoint_with_version


class TestEndpointOpenAPISpec(ClickhouseTestMixin, APIBaseTest):
    """Tests for the OpenAPI specification generation endpoint."""

    def setUp(self):
        super().setUp()
        self.sample_hogql_query = {
            "kind": "HogQLQuery",
            "query": "SELECT count(1) FROM events",
        }

    def test_openapi_spec_basic(self):
        """Test generating OpenAPI spec for a basic endpoint."""
        create_endpoint_with_version(
            name="basic-endpoint",
            team=self.team,
            query=self.sample_hogql_query,
            description="A basic test endpoint",
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/basic-endpoint/openapi.json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        self.assertEqual(spec["openapi"], "3.0.3")
        self.assertEqual(spec["info"]["title"], "basic-endpoint")
        self.assertEqual(spec["info"]["description"], "A basic test endpoint")
        self.assertEqual(spec["info"]["version"], "1")

        self.assertIn("servers", spec)
        self.assertEqual(len(spec["servers"]), 1)

        run_path = f"/api/environments/{self.team.id}/endpoints/basic-endpoint/run"
        self.assertIn(run_path, spec["paths"])

        post_op = spec["paths"][run_path]["post"]
        self.assertEqual(post_op["operationId"], "run_basic_endpoint")
        self.assertIn("requestBody", post_op)
        self.assertIn("responses", post_op)
        self.assertIn("200", post_op["responses"])

        response_schema = post_op["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertIn("results", response_schema["properties"])
        self.assertEqual(response_schema["properties"]["results"]["type"], "array")

    def test_openapi_spec_with_variables(self):
        """Test that HogQL endpoints with variables include variables in the schema."""
        from posthog.models.insight_variable import InsightVariable

        variable = InsightVariable.objects.create(
            team=self.team,
            name="Country Filter",
            code_name="country",
            type=InsightVariable.Type.STRING,
            default_value="US",
        )

        query_with_variables = {
            "kind": "HogQLQuery",
            "query": "SELECT * FROM events WHERE properties.$country = {variables.country}",
            "variables": {str(variable.id): {"variableId": str(variable.id), "code_name": "country", "value": "US"}},
        }

        create_endpoint_with_version(
            name="endpoint-with-vars",
            team=self.team,
            query=query_with_variables,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/endpoint-with-vars/openapi.json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        # Check that EndpointRunRequest schema has variables reference
        endpoint_schema = spec["components"]["schemas"]["EndpointRunRequest"]
        self.assertIn("variables", endpoint_schema["properties"])

        # Check Variables schema is defined with the variable
        self.assertIn("Variables", spec["components"]["schemas"])
        variables_schema = spec["components"]["schemas"]["Variables"]
        self.assertEqual(variables_schema["type"], "object")
        self.assertIn("country", variables_schema["properties"])

    def test_openapi_spec_dashboard_filter_schema(self):
        """Test that DashboardFilter schema includes date_from and date_to."""
        create_endpoint_with_version(
            name="filter-test-endpoint",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/filter-test-endpoint/openapi.json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        # Check DashboardFilter schema
        self.assertIn("DashboardFilter", spec["components"]["schemas"])
        filter_schema = spec["components"]["schemas"]["DashboardFilter"]
        self.assertIn("date_from", filter_schema["properties"])
        self.assertIn("date_to", filter_schema["properties"])
        self.assertIn("properties", filter_schema["properties"])

    def test_openapi_spec_not_found(self):
        """Test that requesting spec for non-existent endpoint returns 404."""
        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/nonexistent/openapi.json/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_openapi_spec_security_scheme(self):
        """Test that the spec includes proper security scheme."""
        create_endpoint_with_version(
            name="secure-endpoint",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/secure-endpoint/openapi.json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        self.assertIn("components", spec)
        self.assertIn("securitySchemes", spec["components"])
        self.assertIn("PersonalAPIKey", spec["components"]["securitySchemes"])
        self.assertEqual(spec["components"]["securitySchemes"]["PersonalAPIKey"]["type"], "http")
        self.assertEqual(spec["components"]["securitySchemes"]["PersonalAPIKey"]["scheme"], "bearer")

    def test_openapi_spec_version_reflects_endpoint_version(self):
        """Test that the spec version matches the endpoint's current version."""
        create_endpoint_with_version(
            name="versioned-endpoint",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
            current_version=3,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/versioned-endpoint/openapi.json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()
        self.assertEqual(spec["info"]["version"], "3")

    def test_openapi_spec_insight_endpoint_with_date_variables(self):
        """Test that non-materialized insight endpoints include date variables in spec."""
        from posthog.schema import EventsNode, TrendsQuery

        create_endpoint_with_version(
            name="trends-endpoint",
            team=self.team,
            query=TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/trends-endpoint/openapi.json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        # Check that EndpointRunRequest schema has variables reference
        endpoint_schema = spec["components"]["schemas"]["EndpointRunRequest"]
        self.assertIn("variables", endpoint_schema["properties"])

        # Check Variables schema is defined with date variables
        self.assertIn("Variables", spec["components"]["schemas"])
        variables_schema = spec["components"]["schemas"]["Variables"]
        self.assertEqual(variables_schema["type"], "object")
        self.assertIn("date_from", variables_schema["properties"])
        self.assertIn("date_to", variables_schema["properties"])

    def test_openapi_spec_insight_endpoint_with_breakdown(self):
        """Test that insight endpoints with breakdown include breakdown property in spec."""
        from posthog.schema import Breakdown, BreakdownFilter, BreakdownType, EventsNode, TrendsQuery

        create_endpoint_with_version(
            name="trends-breakdown",
            team=self.team,
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser", type=BreakdownType.EVENT)]),
            ).model_dump(),
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/trends-breakdown/openapi.json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        # Check Variables schema includes breakdown property
        self.assertIn("Variables", spec["components"]["schemas"])
        variables_schema = spec["components"]["schemas"]["Variables"]
        self.assertIn("$browser", variables_schema["properties"])
        # Non-materialized should also have date variables
        self.assertIn("date_from", variables_schema["properties"])
        self.assertIn("date_to", variables_schema["properties"])

    def test_openapi_spec_hogql_without_variables(self):
        """Test that HogQL endpoints without variables don't include Variables schema."""
        create_endpoint_with_version(
            name="simple-hogql",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/simple-hogql/openapi.json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        # Should not have Variables schema since no variables defined
        self.assertNotIn("Variables", spec["components"]["schemas"])
