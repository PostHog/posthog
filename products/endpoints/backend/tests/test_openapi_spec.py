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

        assert response.status_code == status.HTTP_200_OK
        spec = response.json()

        assert spec["openapi"] == "3.0.3"
        assert spec["info"]["title"] == "basic-endpoint"
        assert spec["info"]["description"] == "A basic test endpoint"
        assert spec["info"]["version"] == "1"

        assert "servers" in spec
        assert len(spec["servers"]) == 1

        run_path = f"/api/projects/{self.team.id}/endpoints/basic-endpoint/run"
        assert run_path in spec["paths"]

        post_op = spec["paths"][run_path]["post"]
        assert post_op["operationId"] == "run_basic_endpoint"
        assert "requestBody" in post_op
        assert "responses" in post_op
        assert "200" in post_op["responses"]

        response_schema = post_op["responses"]["200"]["content"]["application/json"]["schema"]
        assert "results" in response_schema["properties"]
        assert response_schema["properties"]["results"]["type"] == "array"

    def test_openapi_spec_with_variables(self):
        from products.product_analytics.backend.models.insight_variable import InsightVariable

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

        assert response.status_code == status.HTTP_200_OK
        spec = response.json()

        endpoint_schema = spec["components"]["schemas"]["EndpointRunRequest"]
        assert "variables" in endpoint_schema["properties"]

        assert "Variables" in spec["components"]["schemas"]
        variables_schema = spec["components"]["schemas"]["Variables"]
        assert variables_schema["type"] == "object"
        assert "country" in variables_schema["properties"]
        assert variables_schema["properties"]["country"]["type"] == "string"

    def test_openapi_spec_variable_types(self):
        from products.product_analytics.backend.models.insight_variable import InsightVariable

        test_cases = [
            (InsightVariable.Type.NUMBER, "number", None),
            (InsightVariable.Type.BOOLEAN, "boolean", None),
            (InsightVariable.Type.DATE, "string", "date"),
        ]

        for var_type, expected_openapi_type, expected_format in test_cases:
            with self.subTest(var_type=var_type):
                variable = InsightVariable.objects.create(
                    team=self.team,
                    name=f"Test {var_type}",
                    code_name=f"test_{var_type.lower()}",
                    type=var_type,
                    default_value="42" if var_type == InsightVariable.Type.NUMBER else None,
                )

                query = {
                    "kind": "HogQLQuery",
                    "query": f"SELECT * FROM events WHERE x = {{variables.test_{var_type.lower()}}}",
                    "variables": {
                        str(variable.id): {
                            "variableId": str(variable.id),
                            "code_name": f"test_{var_type.lower()}",
                            "value": None,
                        }
                    },
                }

                ep_name = f"typed-var-{var_type.lower()}"
                create_endpoint_with_version(
                    name=ep_name,
                    team=self.team,
                    query=query,
                    created_by=self.user,
                    is_active=True,
                )

                response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{ep_name}/openapi.json/")
                assert response.status_code == status.HTTP_200_OK
                spec = response.json()

                var_schema = spec["components"]["schemas"]["Variables"]["properties"][f"test_{var_type.lower()}"]
                assert var_schema["type"] == expected_openapi_type
                if expected_format:
                    assert var_schema["format"] == expected_format

    def test_openapi_spec_refresh_enum(self):
        create_endpoint_with_version(
            name="refresh-test",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/refresh-test/openapi.json/")
        assert response.status_code == status.HTTP_200_OK
        spec = response.json()

        refresh_schema = spec["components"]["schemas"]["EndpointRunRequest"]["properties"]["refresh"]
        assert refresh_schema["enum"] == ["cache", "force", "direct"]
        assert refresh_schema["default"] == "cache"

    def test_openapi_spec_includes_limit_and_debug(self):
        create_endpoint_with_version(
            name="fields-test",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/fields-test/openapi.json/")
        assert response.status_code == status.HTTP_200_OK
        spec = response.json()

        props = spec["components"]["schemas"]["EndpointRunRequest"]["properties"]
        assert "limit" in props
        assert props["limit"]["type"] == "integer"
        assert "debug" in props
        assert props["debug"]["type"] == "boolean"

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

        assert response.status_code == status.HTTP_200_OK
        spec = response.json()

        # Check DashboardFilter schema
        assert "DashboardFilter" in spec["components"]["schemas"]
        filter_schema = spec["components"]["schemas"]["DashboardFilter"]
        assert "date_from" in filter_schema["properties"]
        assert "date_to" in filter_schema["properties"]
        assert "properties" in filter_schema["properties"]

    def test_openapi_spec_not_found(self):
        """Test that requesting spec for non-existent endpoint returns 404."""
        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/nonexistent/openapi.json/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

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

        assert response.status_code == status.HTTP_200_OK
        spec = response.json()

        assert "components" in spec
        assert "securitySchemes" in spec["components"]
        assert "PersonalAPIKey" in spec["components"]["securitySchemes"]
        assert spec["components"]["securitySchemes"]["PersonalAPIKey"]["type"] == "http"
        assert spec["components"]["securitySchemes"]["PersonalAPIKey"]["scheme"] == "bearer"

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

        assert response.status_code == status.HTTP_200_OK
        spec = response.json()
        assert spec["info"]["version"] == "3"

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

        assert response.status_code == status.HTTP_200_OK
        spec = response.json()

        # Check that EndpointRunRequest schema has variables reference
        endpoint_schema = spec["components"]["schemas"]["EndpointRunRequest"]
        assert "variables" in endpoint_schema["properties"]

        # Check Variables schema is defined with date variables
        assert "Variables" in spec["components"]["schemas"]
        variables_schema = spec["components"]["schemas"]["Variables"]
        assert variables_schema["type"] == "object"
        assert "date_from" in variables_schema["properties"]
        assert "date_to" in variables_schema["properties"]

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

        assert response.status_code == status.HTTP_200_OK
        spec = response.json()

        # Check Variables schema includes breakdown property
        assert "Variables" in spec["components"]["schemas"]
        variables_schema = spec["components"]["schemas"]["Variables"]
        assert "$browser" in variables_schema["properties"]
        # Non-materialized should also have date variables
        assert "date_from" in variables_schema["properties"]
        assert "date_to" in variables_schema["properties"]

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

        assert response.status_code == status.HTTP_200_OK
        spec = response.json()

        # Should not have Variables schema since no variables defined
        assert "Variables" not in spec["components"]["schemas"]
