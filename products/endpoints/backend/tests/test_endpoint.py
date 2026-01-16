from datetime import datetime
from time import sleep
from typing import Any
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.case import skip

from parameterized import parameterized
from rest_framework import status

from posthog.schema import EndpointLastExecutionTimesRequest, EventsNode, TrendsQuery

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.insight_variable import InsightVariable
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal

from products.endpoints.backend.models import Endpoint


class TestEndpoint(ClickhouseTestMixin, APIBaseTest):
    ENDPOINT = "endpoints"

    def setUp(self):
        super().setUp()
        self.api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Test API Key",
            secure_value=hash_key_value(self.api_key),
        )
        self.sample_hogql_query = {
            "explain": None,
            "filters": None,
            "kind": "HogQLQuery",
            "modifiers": None,
            "name": None,
            "query": "SELECT count(1) FROM query_log",
            "response": None,
            "tags": None,
            "values": None,
            "variables": None,
            "version": None,
        }
        self.sample_insight_query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode"}],
        }

    def test_create_hogql_endpoint(self):
        """Test creating a endpoint successfully."""
        data = {
            "name": "test_query",
            "description": "Test query description",
            "query": self.sample_hogql_query,
        }

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        response_data = response.json()

        self.assertEqual("test_query", response_data["name"])
        self.assertEqual(self.sample_hogql_query, response_data["query"])
        self.assertEqual("Test query description", response_data["description"])
        self.assertTrue(response_data["is_active"])
        self.assertIn("id", response_data)
        self.assertIn("endpoint_path", response_data)
        self.assertIn("created_at", response_data)
        self.assertIn("updated_at", response_data)

        self.assertIsNone(response_data["derived_from_insight"])

        # Verify it was saved to database
        endpoint = Endpoint.objects.get(name="test_query", team=self.team)
        self.assertEqual(endpoint.query, self.sample_hogql_query)
        self.assertEqual(endpoint.created_by, self.user)
        self.assertIsNone(endpoint.derived_from_insight)

        # Activity log created
        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="Endpoint", activity="created")
        self.assertEqual(logs.count(), 1, list(logs.values("activity", "scope", "item_id")))
        log = logs.latest("created_at")
        self.assertEqual(log.item_id, str(endpoint.id))
        assert log.detail is not None
        self.assertEqual(log.detail.get("name"), "test_query")

    @skip("Validation of HogQL not implemented yet")
    def test_cannot_create_endpoint_with_invalid_sql(self):
        """Test creating an endpoint with invalid HogQL fails."""
        data = {
            "name": "test_query",
            "description": "Test query description",
            "query": {"kind": "HogQLQuery", "query": "selet 100"},  # intentionally wrong spelling
        }

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code, response.json())
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")

    def test_create_insight_endpoint(self):
        data = {
            "name": "test_insight_query",
            "description": "Test query description",
            "query": self.sample_insight_query,
        }

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())

    def test_update_endpoint(self):
        """Test updating an existing endpoint."""
        endpoint = Endpoint.objects.create(
            name="update_test",
            team=self.team,
            query=self.sample_hogql_query,
            description="Original description",
            created_by=self.user,
        )

        updated_data = {
            "description": "Updated description",
            "is_active": False,
            "query": {"kind": "HogQLQuery", "query": "SELECT 1"},
        }

        response = self.client.put(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/", updated_data, format="json"
        )

        response_data = response.json()
        self.assertEqual(status.HTTP_200_OK, response.status_code, response_data)

        self.assertEqual("update_test", response_data["name"])
        self.assertEqual("Updated description", response_data["description"])
        self.assertFalse(response_data["is_active"])
        want_query = {
            "explain": None,
            "filters": None,
            "kind": "HogQLQuery",
            "modifiers": None,
            "name": None,
            "query": "SELECT 1",
            "response": None,
            "tags": None,
            "values": None,
            "variables": None,
            "version": None,
        }
        self.assertEqual(want_query, response_data["query"])

        # Verify database was updated
        endpoint.refresh_from_db()
        self.assertEqual(endpoint.description, "Updated description")
        self.assertFalse(endpoint.is_active)

        # Activity log updated with changes
        logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="Endpoint",
            activity="updated",
            item_id=str(endpoint.id),
        )
        self.assertEqual(logs.count(), 1, list(logs.values("activity", "detail")))
        log = logs.latest("created_at")
        assert log.detail is not None

        self.assertEqual("updated", log.activity)
        changes = log.detail.get("changes", [])
        changed_fields = {c.get("field") for c in changes}
        self.assertIn("description", changed_fields)
        self.assertIn("is_active", changed_fields)

    def test_delete_endpoint(self):
        """Test deleting a endpoint."""
        endpoint = Endpoint.objects.create(
            name="delete_test",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/endpoints/delete_test/")

        self.assertIn(response.status_code, [status.HTTP_204_NO_CONTENT, status.HTTP_200_OK])
        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="Endpoint", activity="deleted")
        self.assertEqual(logs.count(), 1, list(logs.values("activity", "scope", "item_id")))
        log = logs.latest("created_at")
        self.assertEqual(log.item_id, str(endpoint.id))
        assert log.detail is not None
        self.assertEqual(log.detail.get("name"), "delete_test")

    def test_invalid_query_name_validation(self):
        """Test validation of invalid query names."""
        data = {
            "name": "invalid@name!",
            "query": self.sample_hogql_query,
        }

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_missing_required_fields(self):
        """Test validation when required fields are missing."""
        data: dict[str, Any] = {"query": self.sample_hogql_query}

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = {"name": "test_query"}

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_name_in_team(self):
        """Test that duplicate names within the same team are not allowed."""
        Endpoint.objects.create(
            name="duplicate_test",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
        )

        data = {
            "name": "duplicate_test",
            "query": {"kind": "HogQLQuery", "query": "SELECT 2"},
        }

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_team_isolation(self):
        """Test that queries are properly isolated between teams."""
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_user = User.objects.create_and_join(self.organization, "other@test.com", None)

        Endpoint.objects.create(
            name="other_team_query",
            team=other_team,
            query=self.sample_hogql_query,
            created_by=other_user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/other_team_query/run/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_filter_by_is_active(self):
        """Test filtering endpoints by is_active status."""
        Endpoint.objects.create(
            name="active_query",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )
        Endpoint.objects.create(
            name="inactive_query",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=False,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/?is_active=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "active_query")
        self.assertTrue(response_data["results"][0]["is_active"])

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/?is_active=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "inactive_query")
        self.assertFalse(response_data["results"][0]["is_active"])

    def test_list_filter_by_created_by(self):
        """Test filtering endpoints by created_by user."""
        other_user = User.objects.create_and_join(self.organization, "other@test.com", None)

        Endpoint.objects.create(
            name="query_by_user1",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
        )
        Endpoint.objects.create(
            name="query_by_user2",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=other_user,
        )

        # Test filtering by first user
        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/?created_by={self.user.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "query_by_user1")

        # Test filtering by second user
        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/?created_by={other_user.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "query_by_user2")

    def test_list_filter_combined(self):
        """Test filtering endpoints by both is_active and created_by."""
        other_user = User.objects.create_and_join(self.organization, "other@test.com", None)

        Endpoint.objects.create(
            name="active_query_user1",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )
        Endpoint.objects.create(
            name="inactive_query_user1",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=False,
        )
        Endpoint.objects.create(
            name="active_query_user2",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=other_user,
            is_active=True,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/endpoints/?is_active=true&created_by={self.user.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "active_query_user1")
        self.assertTrue(response_data["results"][0]["is_active"])

    def test_list_no_filters(self):
        """Test listing all endpoints without filters."""
        Endpoint.objects.create(
            name="query1",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=True,
        )
        Endpoint.objects.create(
            name="query2",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=False,
        )

        # Test without any filters - should return all queries
        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)
        query_names = {q["name"] for q in response_data["results"]}
        self.assertEqual(query_names, {"query1", "query2"})

    def test_create_endpoint_with_comprehensive_trends_query(self):
        """Test creating a endpoint with a comprehensive TrendsQuery containing many fields."""
        comprehensive_trends_query = {
            "kind": "TrendsQuery",
            "series": [
                {
                    "kind": "EventsNode",
                    "event": "$pageview",
                    "custom_name": "Page Views",
                    "math": "total",
                    "fixedProperties": [
                        {"key": "$current_url", "operator": "icontains", "type": "event", "value": "posthog.com"}
                    ],
                },
                {"kind": "EventsNode", "event": "$autocapture", "custom_name": "Autocapture Events", "math": "dau"},
            ],
            "dateRange": {"date_from": "2025-01-01", "date_to": "2025-01-31", "explicitDate": True},
            "interval": "week",
            "breakdownFilter": {
                "breakdown": "$geoip_country_code",
                "breakdown_type": "event",
                "breakdown_limit": 10,
                "breakdown_hide_other_aggregation": False,
                "breakdown_normalize_url": True,
            },
            "compareFilter": {"compare": True, "compare_to": "-1m"},
            "trendsFilter": {
                "display": "ActionsLineGraph",
                "showLegend": True,
                "showValuesOnSeries": True,
                "showLabelsOnSeries": False,
                "showPercentStackView": False,
                "showMultipleYAxes": True,
                "aggregationAxisFormat": "numeric",
                "aggregationAxisPrefix": "$",
                "aggregationAxisPostfix": " USD",
                "decimalPlaces": 2,
                "minDecimalPlaces": 1,
                "confidenceLevel": 0.95,
                "showConfidenceIntervals": True,
                "showMovingAverage": False,
                "movingAverageIntervals": 7,
                "smoothingIntervals": 3,
                "showTrendLines": True,
                "showAlertThresholdLines": False,
                "yAxisScaleType": "linear",
                "formula": "A + B",
                "formulas": ["A", "B", "A + B"],
                "goalLines": [{"value": 1000, "label": "Target"}],
                "hiddenLegendIndexes": [1],
            },
            "properties": [
                {"key": "$browser", "operator": "in", "type": "event", "value": ["Chrome", "Firefox", "Safari"]},
                {"key": "email", "operator": "is_set", "type": "person", "value": None},
            ],
            "filterTestAccounts": True,
            "samplingFactor": 0.1,
            "aggregation_group_type_index": 1,
            "dataColorTheme": 0.5,
            "version": 2,
        }

        data = {
            "name": "comprehensive_trends_test",
            "description": "A comprehensive trends query with many fields populated",
            "query": comprehensive_trends_query,
        }

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        response_data = response.json()

        # Verify all the key fields are preserved
        self.assertEqual("comprehensive_trends_test", response_data["name"])
        self.assertEqual("A comprehensive trends query with many fields populated", response_data["description"])
        self.assertTrue(response_data["is_active"])

        saved_query = response_data["query"]
        self.assertEqual("TrendsQuery", saved_query["kind"])
        self.assertEqual("week", saved_query["interval"])
        self.assertEqual(2, len(saved_query["series"]))
        self.assertEqual("$pageview", saved_query["series"][0]["event"])
        self.assertEqual("Page Views", saved_query["series"][0]["custom_name"])

        # Verify date range
        self.assertEqual("2025-01-01", saved_query["dateRange"]["date_from"])
        self.assertEqual("2025-01-31", saved_query["dateRange"]["date_to"])
        self.assertTrue(saved_query["dateRange"]["explicitDate"])

        self.assertEqual("$geoip_country_code", saved_query["breakdownFilter"]["breakdown"])
        self.assertEqual("event", saved_query["breakdownFilter"]["breakdown_type"])
        self.assertEqual(10, saved_query["breakdownFilter"]["breakdown_limit"])

        self.assertTrue(saved_query["compareFilter"]["compare"])
        self.assertEqual("-1m", saved_query["compareFilter"]["compare_to"])

        trends_filter = saved_query["trendsFilter"]
        self.assertEqual("ActionsLineGraph", trends_filter["display"])
        self.assertTrue(trends_filter["showLegend"])
        self.assertTrue(trends_filter["showValuesOnSeries"])
        self.assertEqual("numeric", trends_filter["aggregationAxisFormat"])
        self.assertEqual("$", trends_filter["aggregationAxisPrefix"])
        self.assertEqual(" USD", trends_filter["aggregationAxisPostfix"])
        self.assertEqual(2, trends_filter["decimalPlaces"])
        self.assertEqual(0.95, trends_filter["confidenceLevel"])
        self.assertEqual("A + B", trends_filter["formula"])
        self.assertEqual(1, len(trends_filter["goalLines"]))
        self.assertEqual(1000, trends_filter["goalLines"][0]["value"])

        self.assertEqual(2, len(saved_query["properties"]))
        self.assertEqual("$browser", saved_query["properties"][0]["key"])
        self.assertEqual("in", saved_query["properties"][0]["operator"])
        self.assertEqual(["Chrome", "Firefox", "Safari"], saved_query["properties"][0]["value"])

        self.assertTrue(saved_query["filterTestAccounts"])
        self.assertEqual(0.1, saved_query["samplingFactor"])
        self.assertEqual(1, saved_query["aggregation_group_type_index"])

        endpoint = Endpoint.objects.get(name="comprehensive_trends_test", team=self.team)
        self.assertEqual(endpoint.created_by, self.user)
        self.assertEqual("TrendsQuery", endpoint.query["kind"])

    def test_get_last_execution_times_empty_names(self):
        """Test getting last execution times with empty names list."""
        data = EndpointLastExecutionTimesRequest(names=[]).model_dump()

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/last_execution_times/", data, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertIn("query_status", response_data, response_data)
        query_status = response_data["query_status"]
        self.assertIn("complete", query_status)
        self.assertIn("results", query_status)

        self.assertIsNone(query_status["results"], query_status)

    def test_get_last_execution_times_after_endpoint_execution(self):
        """Test getting last execution times with endpoint names after they have been executed."""
        Endpoint.objects.create(
            name="test_query_1",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
        )
        Endpoint.objects.create(
            name="test_query_2",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 2"},
            created_by=self.user,
            is_active=True,
        )

        # Execute the endpoints using API key to generate query_log entries with is_personal_api_key_request=true
        response1 = self.client.get(
            f"/api/environments/{self.team.id}/endpoints/test_query_1/run/",
            HTTP_AUTHORIZATION=f"Bearer {self.api_key}",
        )
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        response2 = self.client.get(
            f"/api/environments/{self.team.id}/endpoints/test_query_2/run/",
            HTTP_AUTHORIZATION=f"Bearer {self.api_key}",
        )
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # wait for the queries to end up in query_log :/
        sleep(3)

        data = {"names": ["test_query_1", "test_query_2", "nonexistent_query"]}
        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/last_execution_times/", data, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        response_data = response.json()

        self.assertIn("query_status", response_data)
        query_status = response_data["query_status"]
        self.assertIn("complete", query_status)
        self.assertIn("results", query_status)
        self.assertIsInstance(query_status["results"], list)

        results = query_status["results"]
        self.assertEqual(len(results), 2, f"Expected 2 results, got {results}")

        query_timestamps = {row[0]: row[1] for row in results if len(row) >= 2}

        self.assertIn("test_query_1", query_timestamps, f"test_query_1 not found in results: {results}")
        self.assertIn("test_query_2", query_timestamps, f"test_query_2 not found in results: {results}")
        self.assertIsNotNone(
            datetime.fromisoformat(query_timestamps["test_query_1"]),
            f"Invalid timestamp format for test_query_1: {query_timestamps['test_query_1']}",
        )
        self.assertIsNotNone(
            datetime.fromisoformat(query_timestamps["test_query_2"]),
            f"Invalid timestamp format for test_query_2: {query_timestamps['test_query_2']}",
        )

    def test_get_last_execution_times_with_nonexistent_query(self):
        """Test getting last execution times with a nonexistent query."""
        data = {"names": ["nonexistent_query"]}

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/last_execution_times/", data, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertIn("query_status", response_data)
        query_status = response_data["query_status"]
        self.assertIsInstance(query_status["results"], list)
        self.assertEqual(len(query_status["results"]), 0)

    def test_get_last_execution_times_of_endpoint_not_executed(self):
        """Test getting last execution times of a endpoint that has not been executed."""
        Endpoint.objects.create(
            name="test_query_1",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
        )

        data = {"names": ["test_query_1"]}

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/last_execution_times/", data, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertIn("query_status", response_data)
        query_status = response_data["query_status"]
        self.assertIsInstance(query_status["results"], list)
        self.assertEqual(len(query_status["results"]), 0, query_status)

    @parameterized.expand(
        [
            ("valid_300s", 300, status.HTTP_201_CREATED, None),
            ("valid_86400s", 86400, status.HTTP_201_CREATED, None),
            ("too_small_30s", 30, status.HTTP_400_BAD_REQUEST, "between 300 and 86400"),
            ("too_small_299s", 299, status.HTTP_400_BAD_REQUEST, "between 300 and 86400"),
            ("too_large_100000s", 100000, status.HTTP_400_BAD_REQUEST, "between 300 and 86400"),
            ("too_large_86401s", 86401, status.HTTP_400_BAD_REQUEST, "between 300 and 86400"),
            ("null_uses_defaults", None, status.HTTP_201_CREATED, None),
        ]
    )
    def test_cache_age_seconds_validation(self, name, cache_age_seconds, expected_status, expected_error_text):
        """Test validation of cache_age_seconds field with various inputs."""
        data = {
            "name": f"cache_test_{name}",
            "query": self.sample_hogql_query,
            "cache_age_seconds": cache_age_seconds,
        }
        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")
        self.assertEqual(response.status_code, expected_status)

        if expected_status == status.HTTP_201_CREATED:
            self.assertEqual(response.json()["cache_age_seconds"], cache_age_seconds)
        elif expected_error_text:
            self.assertIn(expected_error_text, str(response.json()))

    @parameterized.expand(
        [
            (
                "hogql_5min",
                {"kind": "HogQLQuery", "query": "SELECT 1 as result"},
                300,  # 5 minute cache age
                4,  # Time within cache (minutes)
                6,  # Time past cache (minutes)
            ),
            (
                "trends_10min",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                    "dateRange": {"date_from": "-7d", "date_to": None},
                    "interval": "day",
                },
                600,  # 10 minute cache age
                8,  # Time within cache (minutes)
                12,  # Time past cache (minutes)
            ),
        ]
    )
    @freeze_time("2025-01-01 12:00:00")
    def test_custom_cache_age_behavior(self, name, query, cache_age_seconds, time_within_cache, time_past_cache):
        """Test that custom cache_age_seconds affects cache staleness for different query types."""
        # Create endpoint with custom cache age
        endpoint = Endpoint.objects.create(
            name=f"custom_cache_{name}",
            team=self.team,
            query=query,
            created_by=self.user,
            is_active=True,
            cache_age_seconds=cache_age_seconds,
        )

        # First execution - should calculate fresh
        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {"debug": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        # Verify it was cached
        self.assertIn("cache_key", response_data)
        self.assertIn("last_refresh", response_data)
        cache_key = response_data["cache_key"]

        # Second execution immediately - should use cache
        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {"debug": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["cache_key"], cache_key)
        self.assertTrue(response_data.get("is_cached", False))

        # Move time forward (still within cache age)
        with freeze_time(f"2025-01-01 12:{time_within_cache:02d}:00"):
            response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()
            self.assertTrue(
                response_data.get("is_cached", False),
                f"Should still use cache at {time_within_cache} minutes",
            )

        # Move time forward (past cache age) - should recalculate
        with freeze_time(f"2025-01-01 12:{time_past_cache:02d}:00"):
            response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()
            # Should have recalculated with fresh data
            self.assertFalse(
                response_data.get("is_cached", True),
                f"Should recalculate after {time_past_cache} minutes",
            )

    @freeze_time("2025-01-01 12:00:00")
    def test_default_cache_age_when_not_set(self):
        """Test that endpoints without cache_age_seconds use default interval-based caching."""
        # Create endpoint WITHOUT custom cache age - should use default (6 hours for day interval)
        endpoint = Endpoint.objects.create(
            name="default_cache_age",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 2 as result"},
            created_by=self.user,
            is_active=True,
            cache_age_seconds=None,  # Use defaults
        )

        # First execution
        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        cache_key = response_data.get("cache_key")

        # Move time forward 5 minutes - should still use cache (default is much longer)
        with freeze_time("2025-01-01 12:05:00"):
            response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()
            self.assertTrue(response_data.get("is_cached", False), "Should use cache with default timing")
            self.assertEqual(response_data.get("cache_key"), cache_key)

    def test_update_cache_age_seconds(self):
        """Test updating cache_age_seconds on an existing endpoint."""
        endpoint = Endpoint.objects.create(
            name="update_cache_test",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            cache_age_seconds=300,
        )

        # Update to different cache age
        updated_data: dict[str, int | None] = {"cache_age_seconds": 600}
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/", updated_data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["cache_age_seconds"], 600)

        endpoint.refresh_from_db()
        self.assertEqual(endpoint.cache_age_seconds, 600)

        # Update to None (use defaults)
        updated_data = {"cache_age_seconds": None}
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/", updated_data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["cache_age_seconds"])

        endpoint.refresh_from_db()
        self.assertIsNone(endpoint.cache_age_seconds)

    def test_create_endpoint_with_insight_reference(self):
        """Test creating an endpoint with a reference to the insight it was created from."""
        data = {
            "name": "test_with_insight",
            "description": "Endpoint created from insight",
            "query": self.sample_hogql_query,
            "derived_from_insight": "abc123xyz",
        }

        response = self.client.post(f"/api/environments/{self.team.id}/endpoints/", data, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        response_data = response.json()

        self.assertEqual("test_with_insight", response_data["name"])
        self.assertEqual("abc123xyz", response_data["derived_from_insight"])
        endpoint = Endpoint.objects.get(name="test_with_insight", team=self.team)
        self.assertEqual(endpoint.derived_from_insight, "abc123xyz")


class TestEndpointExecution(ClickhouseTestMixin, APIBaseTest):
    ENDPOINT = "endpoints"

    def setUp(self):
        super().setUp()
        self.sample_hogql_query = {
            "explain": None,
            "filters": None,
            "kind": "HogQLQuery",
            "modifiers": None,
            "name": None,
            "query": "SELECT count(1) FROM query_log",
            "response": None,
            "tags": None,
            "values": None,
            "variables": None,
            "version": None,
        }
        self.sample_insight_query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode"}],
        }

    def test_execute_endpoint(self):
        """Test executing a endpoint successfully."""
        Endpoint.objects.create(
            name="execute_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1 as result"},
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/execute_test/run/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertIn("results", response_data)
        self.assertIsInstance(response_data["results"], list)

    def test_execute_inactive_query(self):
        """Test that inactive queries cannot be executed."""
        Endpoint.objects.create(
            name="inactive_test",
            team=self.team,
            query=self.sample_hogql_query,
            created_by=self.user,
            is_active=False,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/inactive_test/run/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # TODO: can we drop this one? yes after test_cant_create_endpoint_with_invalid_sql is green
    def test_execute_query_with_invalid_sql(self):
        """Test error handling when executing query with invalid SQL."""
        Endpoint.objects.create(
            name="invalid_sql_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT FROM invalid_syntax"},
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/invalid_sql_test/run/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.json())

    def test_execute_query_with_variables(self):
        """Test executing a endpoint with variables."""
        variable = InsightVariable.objects.create(
            team=self.team,
            name="From Date",
            code_name="from_date",
            type=InsightVariable.Type.DATE,
            default_value="2025-01-01",
        )

        query_with_variables = {
            "kind": "HogQLQuery",
            "query": "select * from events where toDate(timestamp) > {variables.from_date}",
            "variables": {
                str(variable.id): {"variableId": str(variable.id), "code_name": "from_date", "value": "2025-01-01"}
            },
        }

        Endpoint.objects.create(
            name="query_with_variables",
            team=self.team,
            query=query_with_variables,
            created_by=self.user,
            is_active=True,
        )

        distinct_id = str(uuid4())

        # add 3 events before 2025-09-18
        for _ in range(0, 3):
            _create_event(
                distinct_id=distinct_id,
                team=self.team,
                event="$event1",
                properties={"$lib": "$web"},
                timestamp=datetime(2025, 9, 10),
            )
        # add 3 events after 2025-09-18
        for _ in range(0, 3):
            _create_event(
                distinct_id=distinct_id,
                team=self.team,
                event="$event2",
                properties={"$lib": "$web"},
                timestamp=datetime(2025, 9, 21),
            )

        request_data = {"variables": {"from_date": "2025-09-18"}}

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/query_with_variables/run/", request_data, format="json"
        )

        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response_data)
        self.assertEqual(len(response_data["results"]), 3)

    def test_execute_insight_endpoint_with_filters_override(self):
        Endpoint.objects.create(
            name="trends_query",
            team=self.team,
            query=TrendsQuery(series=[EventsNode()]).model_dump(),
            created_by=self.user,
            is_active=True,
        )
        request_data = {
            "filters_override": {
                "date_from": "2025-09-18",
                "date_to": "2025-09-21",
                "properties": [{"type": "event", "operator": "exact", "key": "event", "value": "$pageview"}],
            },
            "debug": True,
        }
        expected_filters = [{"key": "event", "label": None, "operator": "exact", "type": "event", "value": "$pageview"}]

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/trends_query/run/", request_data, format="json"
        )
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response_data)
        self.assertEqual(response_data["resolved_date_range"]["date_from"], "2025-09-18T00:00:00Z")
        self.assertEqual(response_data["resolved_date_range"]["date_to"], "2025-09-21T23:59:59.999999Z")
        self.assertEqual(response_data["results"][0]["filter"]["properties"], expected_filters)

    def test_execute_insight_endpoint_with_query_override(self):
        """Test executing a endpoint with TrendsQuery override containing key fields."""
        trends_query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
            "dateRange": {"date_from": "2025-01-01", "date_to": "2025-01-20"},
            "interval": "week",
            "breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event", "breakdown_limit": 5},
            "compareFilter": {"compare": True, "compare_to": "-1d"},
            "trendsFilter": {"display": "ActionsLineGraph", "showLegend": True, "decimalPlaces": 1},
            "properties": [{"key": "$current_url", "operator": "icontains", "type": "event", "value": "posthog.com"}],
            "filterTestAccounts": False,
            "samplingFactor": 0.5,
        }

        Endpoint.objects.create(
            name="trends_execution_test",
            team=self.team,
            query=trends_query,
            created_by=self.user,
            is_active=True,
        )

        override_payload = {
            "query_override": {
                "interval": "hour",
                "series": [
                    {"kind": "EventsNode", "event": "$pageview", "math": "total"},
                    {"kind": "EventsNode", "event": "$autocapture", "math": "dau"},
                ],
                "dateRange": {"date_from": "2025-01-01", "date_to": "2025-01-02"},
            }
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/trends_execution_test/run/", override_payload, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        response_data = response.json()

        self.assertIn("results", response_data)
        self.assertIsInstance(response_data["results"], list)

        # TODO: make this more specific
        if response_data["results"]:
            first_series_result = response_data["results"][0]
            self.assertEqual(first_series_result["interval"], "hour")
            self.assertEqual(len(first_series_result["data"]), 25)

    def test_execute_hogql_query_with_override_validation_error(self):
        """Test that executing a HogQL query with query_override raises a validation error."""
        hogql_query = {"kind": "HogQLQuery", "query": "SELECT count(1) FROM events"}

        Endpoint.objects.create(
            name="hogql_validation_test",
            team=self.team,
            query=hogql_query,
            created_by=self.user,
            is_active=True,
        )

        # Try to execute with query_override (should fail)
        override_payload = {"query_override": {"query": "SELECT count(2) FROM events"}}

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/hogql_validation_test/run/", override_payload, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        response_data = response.json()
        self.assertEqual("validation_error", response_data["type"])

    @parameterized.expand(
        [
            ("without_variable_override", None, 0),
            ("with_variable_override", {"test_var": "yes"}, 1),
        ]
    )
    def test_execute_endpoint_with_variable_filtering(self, _name, variables, expected_result_count):
        variable = InsightVariable.objects.create(
            team=self.team,
            name="Test Variable",
            code_name="test_var",
            type=InsightVariable.Type.STRING,
            default_value="no",
        )

        query_with_variable = {
            "kind": "HogQLQuery",
            "query": "SELECT 1 WHERE {variables.test_var} = 'yes'",
            "variables": {
                str(variable.id): {
                    "variableId": str(variable.id),
                    "code_name": "test_var",
                    "value": "no",
                }
            },
        }

        Endpoint.objects.create(
            name="variable_filter_test",
            team=self.team,
            query=query_with_variable,
            created_by=self.user,
            is_active=True,
        )

        request_data = {"variables": variables} if variables else {}

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/variable_filter_test/run/", request_data, format="json"
        )

        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response_data)
        self.assertEqual(len(response_data["results"]), expected_result_count)


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
        Endpoint.objects.create(
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

        Endpoint.objects.create(
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

    def test_openapi_spec_insight_query(self):
        """Test that insight queries include query_override in the schema."""
        insight_query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
        }

        Endpoint.objects.create(
            name="trends-endpoint",
            team=self.team,
            query=insight_query,
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/trends-endpoint/openapi.json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spec = response.json()

        # Check EndpointRunRequest schema in components
        endpoint_schema = spec["components"]["schemas"]["EndpointRunRequest"]
        self.assertIn("query_override", endpoint_schema["properties"])
        self.assertIn("filters_override", endpoint_schema["properties"])

    def test_openapi_spec_dashboard_filter_schema(self):
        """Test that DashboardFilter schema includes date_from and date_to."""
        Endpoint.objects.create(
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
        Endpoint.objects.create(
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
        Endpoint.objects.create(
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
