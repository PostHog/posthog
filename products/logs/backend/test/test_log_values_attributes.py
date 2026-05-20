import os
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.clickhouse.client import sync_execute


class TestLogValuesAttributesTimezones(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            sql = ""
            for line in f:
                log_item = json.loads(line)
                log_item["team_id"] = cls.team.id
                sql += json.dumps(log_item) + "\n"
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {sql}
            """)

    def test_log_values_query_consistency_across_timezones(self):
        """Test that the same values and attributes query returns consistent results across different team timezones"""

        timezones_to_test = ["UTC", "America/Los_Angeles", "Europe/London", "Asia/Tokyo"]

        query_params = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "key": "level",
            "attribute_type": "log",
            "search": "",
        }

        values_results_by_timezone = {}
        attributes_results_by_timezone = {}

        for tz in timezones_to_test:
            self.team.timezone = tz
            self.team.save()

            response = self.client.get(f"/api/projects/{self.team.id}/logs/values", query_params)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            values_results_by_timezone[tz] = response.json()["results"]

            response = self.client.get(f"/api/projects/{self.team.id}/logs/attributes", query_params)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            attributes_results_by_timezone[tz] = response.json()

        base_values_result = values_results_by_timezone["UTC"]
        base_attributes_result = attributes_results_by_timezone["UTC"]["results"]
        for tz, result in values_results_by_timezone.items():
            with self.subTest(timezone=tz):
                self.assertEqual(len(result), len(base_values_result), f"Results length mismatch for timezone {tz}")
                base_values = {r["name"] for r in base_values_result}
                tz_values = {r["name"] for r in result}
                self.assertEqual(base_values, tz_values, f"Log level values mismatch for timezone {tz}")

        for tz, result in attributes_results_by_timezone.items():
            result = result["results"]
            with self.subTest(timezone=tz):
                self.assertEqual(len(result), len(base_attributes_result), f"Results length mismatch for timezone {tz}")
                base_attributes = {r["name"] for r in base_attributes_result}
                tz_attributes = {r["name"] for r in result}
                self.assertEqual(base_attributes, tz_attributes, f"Log level attributes mismatch for timezone {tz}")

    def test_log_values_query_with_value_filter_no_service_name(self):
        """Test that the value parameter correctly filters log values without service_name filtering"""

        query_params = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "key": "level",
            "attribute_type": "log",
            "value": "or",
        }

        response = self.client.get(f"/api/projects/{self.team.pk}/logs/values", query_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]

        for result in results:
            self.assertIn("or", result["name"].lower(), f"Value '{result['name']}' should contain 'or'")

        value_names = {r["name"] for r in results}
        self.assertIn("more", value_names, "Should include 'more' level")
        self.assertIn("error", value_names, "Should include 'error' level")

    def test_log_values_query_with_value_filter_with_service_name(self):
        """Test that the value parameter correctly filters log values with service_name filtering"""

        query_params = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "key": "level",
            "attribute_type": "log",
            "value": "DE",
            "serviceNames": '["argo-rollouts"]',
        }

        response = self.client.get(f"/api/projects/{self.team.pk}/logs/values", query_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]

        for result in results:
            self.assertIn("de", result["name"].lower(), f"Value '{result['name']}' should contain 'de'")

        self.assertGreater(len(results), 0, "Should return at least one result")

    def test_log_values_query_with_value_filter_no_matches(self):
        query_params = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "key": "level",
            "attribute_type": "log",
            "value": "DE",
            "serviceNames": '["cdp-api"]',
        }

        response = self.client.get(f"/api/projects/{self.team.pk}/logs/values", query_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]
        self.assertEqual(len(results), 0, "Should return no results for non-existent value filter")

    def test_log_values_query_with_empty_value_filter(self):
        """Test that empty value parameter returns all values (no filtering)"""

        # First get all values without filter
        query_params_all = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "key": "level",
            "attribute_type": "log",
        }

        response_all = self.client.get(f"/api/projects/{self.team.pk}/logs/values", query_params_all)
        self.assertEqual(response_all.status_code, status.HTTP_200_OK)
        all_results = response_all.json()["results"]

        query_params_empty = {
            **query_params_all,
            "value": "",
        }

        response_empty = self.client.get(f"/api/projects/{self.team.pk}/logs/values", query_params_empty)
        self.assertEqual(response_empty.status_code, status.HTTP_200_OK)
        empty_results = response_empty.json()["results"]

        self.assertEqual(len(all_results), len(empty_results), "Empty value filter should return all values")

        all_names = {r["name"] for r in all_results}
        empty_names = {r["name"] for r in empty_results}
        self.assertEqual(all_names, empty_names, "Empty value filter should return same values as no filter")
        self.assertEqual(set(all_names), {"info", "DEBUG", "PING", "more", "error"})

    def test_log_attributes_search_values_off_by_default(self):
        """Searching with `search_values` unset should match attribute keys only."""

        query_params = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "attribute_type": "resource",
            "search": "argo-rollouts-dashboard",
        }

        response = self.client.get(f"/api/projects/{self.team.pk}/logs/attributes", query_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]
        # No attribute key contains "argo-rollouts-dashboard", so without value search the result is empty.
        self.assertEqual(results, [], "search_values defaults to false — value-only matches must not surface")

    def test_log_attributes_search_values_finds_match_on_value(self):
        """When `search_values=true`, matches against attribute_value should surface with matchedOn='value'."""

        query_params = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "attribute_type": "resource",
            "search": "argo-rollouts-dashboard",
            "search_values": "true",
        }

        response = self.client.get(f"/api/projects/{self.team.pk}/logs/attributes", query_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]
        self.assertGreater(len(results), 0, "Expected value-based matches for argo-rollouts-dashboard")

        for entry in results:
            self.assertIn("matchedOn", entry)
            self.assertIn(entry["matchedOn"], ("key", "value"))
            if entry["matchedOn"] == "value":
                self.assertTrue(entry.get("matchedValue"), "Value matches should expose the matched sample value")
                self.assertIn("argo-rollouts-dashboard", (entry["matchedValue"] or "").lower())

        # All keys here match purely on value (no attribute key contains "argo-rollouts-dashboard").
        self.assertTrue(any(r["matchedOn"] == "value" for r in results))

    def test_log_attributes_search_values_skipped_for_short_search(self):
        """Searches under 4 characters should never trigger value matching, even with `search_values=true`."""

        # "arg" (3 chars) is a substring of values like "argo-rollouts-dashboard", but value
        # search is gated to >= 4 chars to avoid scanning attribute_value on broad queries.
        query_params = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "attribute_type": "resource",
            "search": "arg",
            "search_values": "true",
        }

        response = self.client.get(f"/api/projects/{self.team.pk}/logs/attributes", query_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]
        for entry in results:
            self.assertNotEqual(
                entry.get("matchedOn"),
                "value",
                "value matches must not surface when search term is shorter than the minimum length",
            )

    def test_log_attributes_search_values_ranks_key_matches_first(self):
        """Key matches must always rank above value matches when both exist."""

        # Search "argo" — `service.name` value is "argo-rollouts" (value match), and several
        # k8s.* keys contain it as substring of their values, but no key literally contains "argo".
        # We assert that whenever a key match is present it appears before any value match.
        query_params = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "attribute_type": "resource",
            "search": "argo",
            "search_values": "true",
        }

        response = self.client.get(f"/api/projects/{self.team.pk}/logs/attributes", query_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]
        match_kinds = [r["matchedOn"] for r in results]

        # Once we hit the first value match, we should never see a key match after it.
        first_value_idx = next((i for i, m in enumerate(match_kinds) if m == "value"), None)
        if first_value_idx is not None:
            tail = match_kinds[first_value_idx:]
            self.assertNotIn("key", tail, "key matches must appear before value matches")

    def test_log_attributes_search_trace_id_before_pid(self):
        """Test that searching attributes for 'id' returns trace_id before pid"""

        query_params = {
            "dateRange": '{"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}',
            "attribute_type": "log",
            "search": "id",
        }

        response = self.client.get(f"/api/projects/{self.team.pk}/logs/attributes", query_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]
        result_names = [r["name"] for r in results]

        self.assertIn("trace_id", result_names, "trace_id should be in results when searching for 'id'")
        self.assertIn("brokers.0.id", result_names, "brokers.0.id should be in results when searching for 'id'")
        self.assertIn("pid", result_names, "pid should be in results when searching for 'id'")

        trace_id_index = result_names.index("trace_id")
        brokers_id_index = result_names.index("brokers.0.id")
        pid_index = result_names.index("pid")
        self.assertLess(
            trace_id_index, brokers_id_index, "trace_id should appear before brokers.0.id when searching for 'id'"
        )
        self.assertLess(brokers_id_index, pid_index, "brokers.0.id should appear before pid when searching for 'id'")
