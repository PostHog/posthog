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
        with open(os.path.join(os.path.dirname(__file__), "test_logs_schema.sql")) as f:
            schema_sql = f.read()
        for sql in schema_sql.split(";"):
            if not sql.strip():
                continue
            sync_execute(sql)
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
            values_results_by_timezone[tz] = response.json()

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

        results = response.json()

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

        results = response.json()

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

        results = response.json()
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
        all_results = response_all.json()

        query_params_empty = {
            **query_params_all,
            "value": "",
        }

        response_empty = self.client.get(f"/api/projects/{self.team.pk}/logs/values", query_params_empty)
        self.assertEqual(response_empty.status_code, status.HTTP_200_OK)
        empty_results = response_empty.json()

        self.assertEqual(len(all_results), len(empty_results), "Empty value filter should return all values")

        all_names = {r["name"] for r in all_results}
        empty_names = {r["name"] for r in empty_results}
        self.assertEqual(all_names, empty_names, "Empty value filter should return same values as no filter")
        self.assertEqual(set(all_names), {"info", "DEBUG", "PING", "more", "error"})
