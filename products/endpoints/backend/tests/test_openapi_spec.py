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

        run_path = f"/api/projects/{self.team.id}/endpoints/basic-endpoint/run"
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

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        endpoint_schema = spec["components"]["schemas"]["EndpointRunRequest"]
        self.assertIn("variables", endpoint_schema["properties"])

        self.assertIn("Variables", spec["components"]["schemas"])
        variables_schema = spec["components"]["schemas"]["Variables"]
        self.assertEqual(variables_schema["type"], "object")
        self.assertIn("country", variables_schema["properties"])
        self.assertEqual(variables_schema["properties"]["country"]["type"], "string")

    def test_openapi_spec_marks_hogql_variables_without_default_as_required(self):
        """Regression for #54605."""
        from products.product_analytics.backend.models.insight_variable import InsightVariable

        with_default = InsightVariable.objects.create(
            team=self.team,
            name="Has Default",
            code_name="has_default",
            type=InsightVariable.Type.STRING,
            default_value="default-value",
        )
        without_default = InsightVariable.objects.create(
            team=self.team,
            name="Required",
            code_name="card_name",
            type=InsightVariable.Type.STRING,
        )

        query_with_mixed_variables = {
            "kind": "HogQLQuery",
            "query": "SELECT * FROM events WHERE name = {variables.card_name}",
            "variables": {
                str(with_default.id): {
                    "variableId": str(with_default.id),
                    "code_name": "has_default",
                    "value": "default-value",
                },
                str(without_default.id): {
                    "variableId": str(without_default.id),
                    "code_name": "card_name",
                },
            },
        }

        create_endpoint_with_version(
            name="endpoint-required-vars",
            team=self.team,
            query=query_with_mixed_variables,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/endpoint-required-vars/openapi.json/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        variables_schema = spec["components"]["schemas"]["Variables"]
        self.assertEqual(variables_schema.get("required"), ["card_name"])
        self.assertNotIn("has_default", variables_schema.get("required", []))

        operation = next(iter(spec["paths"].values()))["post"]
        self.assertTrue(operation["requestBody"]["required"])

        # `variables` itself must be required on EndpointRunRequest, otherwise
        # a client sending {} passes validation without supplying card_name.
        request_schema = spec["components"]["schemas"]["EndpointRunRequest"]
        self.assertIn("variables", request_schema.get("required", []))

    def test_openapi_spec_keeps_request_body_optional_when_all_variables_have_defaults(self):
        """When every HogQL variable has a default value, nothing is required."""
        from products.product_analytics.backend.models.insight_variable import InsightVariable

        variable = InsightVariable.objects.create(
            team=self.team,
            name="Country Filter",
            code_name="country",
            type=InsightVariable.Type.STRING,
            default_value="US",
        )

        query = {
            "kind": "HogQLQuery",
            "query": "SELECT * FROM events WHERE properties.$country = {variables.country}",
            "variables": {str(variable.id): {"variableId": str(variable.id), "code_name": "country", "value": "US"}},
        }

        create_endpoint_with_version(
            name="endpoint-optional-vars",
            team=self.team,
            query=query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/endpoint-optional-vars/openapi.json/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        variables_schema = spec["components"]["schemas"]["Variables"]
        self.assertNotIn("required", variables_schema)

        operation = next(iter(spec["paths"].values()))["post"]
        self.assertFalse(operation["requestBody"]["required"])

        request_schema = spec["components"]["schemas"]["EndpointRunRequest"]
        self.assertNotIn("variables", request_schema.get("required", []))

    def test_build_variables_schema_marks_breakdown_required_on_insight(self):
        """The spec marks breakdown variables required on both inline and materialized
        insight endpoints so generated clients always send them; run-time enforcement
        currently applies to materialized endpoints only."""
        from products.endpoints.backend.openapi import _build_variables_schema

        trends_query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
            "breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event"},
        }

        schema = _build_variables_schema(trends_query, is_materialized=True, team_id=self.team.id)
        assert schema is not None
        self.assertIn("$browser", schema["properties"])
        self.assertEqual(schema.get("required"), ["$browser"])

        schema_non_materialized = _build_variables_schema(trends_query, is_materialized=False, team_id=self.team.id)
        assert schema_non_materialized is not None
        self.assertIn("$browser", schema_non_materialized["properties"])
        self.assertEqual(schema_non_materialized.get("required"), ["$browser"])

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
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                spec = response.json()

                var_schema = spec["components"]["schemas"]["Variables"]["properties"][f"test_{var_type.lower()}"]
                self.assertEqual(var_schema["type"], expected_openapi_type)
                if expected_format:
                    self.assertEqual(var_schema["format"], expected_format)

    def test_openapi_spec_refresh_enum(self):
        create_endpoint_with_version(
            name="refresh-test",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/refresh-test/openapi.json/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        refresh_schema = spec["components"]["schemas"]["EndpointRunRequest"]["properties"]["refresh"]
        self.assertEqual(refresh_schema["enum"], ["cache", "force", "direct"])
        self.assertEqual(refresh_schema["default"], "cache")

    def test_openapi_spec_includes_limit_and_debug(self):
        create_endpoint_with_version(
            name="fields-test",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/fields-test/openapi.json/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        props = spec["components"]["schemas"]["EndpointRunRequest"]["properties"]
        self.assertIn("limit", props)
        self.assertEqual(props["limit"]["type"], "integer")
        self.assertIn("debug", props)
        self.assertEqual(props["debug"]["type"], "boolean")

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


class TestEndpointOpenAPIRequiredVariables(ClickhouseTestMixin, APIBaseTest):
    """The Variables schema must surface which variables are required vs optional so
    generated client SDKs reflect the real /run contract. Required breakdowns enforce; optional
    breakdowns may be omitted."""

    def _get(self, name: str) -> dict:
        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{name}/openapi.json/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        schemas = response.json()["components"]["schemas"]
        self.assertIn("Variables", schemas, f"Variables schema missing for endpoint '{name}'")
        return schemas["Variables"]

    def _create_trends(self, name: str, breakdowns: list[dict], optional: list[str] | None = None):
        endpoint = create_endpoint_with_version(
            name=name,
            team=self.team,
            query={
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode"}],
                "breakdownFilter": {"breakdowns": breakdowns},
            },
            created_by=self.user,
            is_active=True,
        )
        if optional:
            version = endpoint.versions.first()
            version.optional_breakdown_properties = optional
            version.save(update_fields=["optional_breakdown_properties"])
        return endpoint

    def test_single_breakdown_required_by_default(self):
        self._create_trends("trends_one_breakdown", [{"property": "$browser", "type": "event"}])

        schema = self._get("trends_one_breakdown")
        self.assertIn("$browser", schema["properties"])
        self.assertIn("$browser", schema.get("required", []))

    def test_single_breakdown_omitted_from_required_when_optional(self):
        self._create_trends("trends_one_optional", [{"property": "$browser", "type": "event"}], optional=["$browser"])

        schema = self._get("trends_one_optional")
        # Property is still surfaced so callers can pass it...
        self.assertIn("$browser", schema["properties"])
        # ...but it's NOT in the required list, so generated SDKs leave it optional.
        # Either no `required` key at all, or `required` exists without $browser.
        self.assertNotIn("$browser", schema.get("required", []))

    def test_multi_breakdown_all_emitted_and_all_required_by_default(self):
        """Every breakdown property must be surfaced and land in `required` until explicitly
        marked optional — historically only the first breakdown was emitted."""
        self._create_trends(
            "trends_multi_breakdown",
            [
                {"property": "$browser", "type": "event"},
                {"property": "$os", "type": "event"},
                {"property": "$country", "type": "event"},
            ],
        )

        schema = self._get("trends_multi_breakdown")
        for prop in ("$browser", "$os", "$country"):
            self.assertIn(prop, schema["properties"], f"property {prop} missing")
            self.assertIn(prop, schema.get("required", []), f"property {prop} not marked required")

    def test_multi_breakdown_required_minus_optional(self):
        self._create_trends(
            "trends_multi_one_optional",
            [
                {"property": "$browser", "type": "event"},
                {"property": "$os", "type": "event"},
            ],
            optional=["$browser"],
        )

        schema = self._get("trends_multi_one_optional")
        self.assertIn("$browser", schema["properties"])
        self.assertIn("$os", schema["properties"])
        self.assertIn("$os", schema.get("required", []))
        self.assertNotIn("$browser", schema.get("required", []))

    def test_all_breakdowns_optional_omits_required_array(self):
        self._create_trends(
            "trends_all_optional",
            [
                {"property": "$browser", "type": "event"},
                {"property": "$os", "type": "event"},
            ],
            optional=["$browser", "$os"],
        )

        schema = self._get("trends_all_optional")
        # No required entries — generated SDK treats every variable as optional.
        self.assertNotIn("required", schema)

    def test_date_variables_never_required(self):
        """date_from / date_to are inline-only convenience variables; they always default at
        runtime and must NOT appear in the required array, even when breakdowns are required."""
        self._create_trends("trends_dates_not_required", [{"property": "$browser", "type": "event"}])

        schema = self._get("trends_dates_not_required")
        self.assertIn("date_from", schema["properties"])
        self.assertIn("date_to", schema["properties"])
        self.assertNotIn("date_from", schema.get("required", []))
        self.assertNotIn("date_to", schema.get("required", []))

    def test_hogql_inline_does_not_mark_variables_required(self):
        """Inline HogQL substitutes defaults/NULLs for missing variables — that's a coherent
        contract. The OpenAPI spec must not mark inline HogQL variables required, or generated
        SDKs would reject calls that are legal at runtime."""
        from products.product_analytics.backend.models.insight_variable import InsightVariable

        InsightVariable.objects.create(
            team=self.team,
            id="00000000-0000-0000-0000-0000000000aa",
            code_name="event_name",
            type="String",
        )
        create_endpoint_with_version(
            name="hogql_inline_no_required",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
                "variables": {
                    "00000000-0000-0000-0000-0000000000aa": {
                        "variableId": "00000000-0000-0000-0000-0000000000aa",
                        "code_name": "event_name",
                        "value": "$pageview",
                    },
                },
            },
            created_by=self.user,
            is_active=True,
        )

        schema = self._get("hogql_inline_no_required")
        self.assertIn("event_name", schema["properties"])
        self.assertNotIn("required", schema)

    def test_hogql_materialized_marks_all_variables_required(self):
        """Materialized HogQL rejects ANY missing variable at run time, defaults included, so the
        spec must mark every variable required — unlike the inline path, which substitutes
        defaults/NULLs and stays optional."""
        from products.endpoints.backend.openapi import _build_variables_schema
        from products.product_analytics.backend.models.insight_variable import InsightVariable

        with_default = InsightVariable.objects.create(
            team=self.team,
            id="00000000-0000-0000-0000-0000000000bb",
            code_name="has_default",
            type="String",
            default_value="fallback",
        )
        no_default = InsightVariable.objects.create(
            team=self.team,
            id="00000000-0000-0000-0000-0000000000cc",
            code_name="event_name",
            type="String",
        )
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
            "variables": {
                str(with_default.id): {
                    "variableId": str(with_default.id),
                    "code_name": "has_default",
                    "value": "fallback",
                },
                str(no_default.id): {"variableId": str(no_default.id), "code_name": "event_name"},
            },
        }

        schema = _build_variables_schema(query, is_materialized=True, team_id=self.team.id)
        assert schema is not None
        self.assertEqual(schema.get("required"), ["event_name", "has_default"])

    def test_deprecation_warning_mentions_marking_breakdown_optional(self):
        """The X-PostHog-Warn deprecation message must mention the optional opt-in (not just
        'use variables instead') — marking the breakdown optional is what callers actually want
        if they were relying on permissive behavior."""
        endpoint = create_endpoint_with_version(
            name="hdr_check",
            team=self.team,
            query={
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode"}],
                "breakdownFilter": {"breakdowns": [{"property": "$browser", "type": "event"}]},
            },
            created_by=self.user,
            is_active=True,
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
            {"filters_override": {"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        warn = response.headers.get("X-PostHog-Warn", "")
        self.assertIn("filters_override is deprecated", warn)
        self.assertIn("optional", warn)
