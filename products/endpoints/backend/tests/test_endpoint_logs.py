from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_log_entries import create_log_entry

from products.endpoints.backend.logs import ENDPOINTS_LOG_SOURCE, build_execution_message, log_endpoint_execution
from products.endpoints.backend.tests.conftest import create_endpoint_with_version


class TestBuildExecutionMessage(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "success_full",
                {
                    "succeeded": True,
                    "execution_type": "materialized",
                    "cache_outcome": "hit",
                    "duration_ms": 142,
                    "rows": 1024,
                    "version": 3,
                },
                "Endpoint executed · path=materialized cache=hit duration_ms=142 rows=1024 version=3",
            ),
            (
                "failure",
                {
                    "succeeded": False,
                    "execution_type": "inline",
                    "error": "ResolutionError",
                    "version": 3,
                },
                "Endpoint execution failed · path=inline version=3 error=ResolutionError",
            ),
            (
                "success_partial_tokens_omitted",
                {"succeeded": True, "execution_type": "ducklake", "version": 1},
                "Endpoint executed · path=ducklake version=1",
            ),
        ]
    )
    def test_build_execution_message(self, _name, kwargs, expected):
        self.assertEqual(build_execution_message(**kwargs), expected)

    def test_produce_failure_is_swallowed(self):
        with mock.patch(
            "products.endpoints.backend.logs.get_producer",
            side_effect=Exception("kafka down"),
        ):
            # Must not raise — emitting a log line is best-effort.
            log_endpoint_execution(
                team_id=1,
                endpoint_id="abc",
                instance_id="exec-1",
                level="INFO",
                message="Endpoint executed",
            )


class TestEndpointExecutionLogs(ClickhouseTestMixin, APIBaseTest):
    def _create_hogql_endpoint(self, name: str, query: str):
        return create_endpoint_with_version(
            name=name,
            team=self.team,
            query={"kind": "HogQLQuery", "query": query},
            created_by=self.user,
            is_active=True,
        )

    def test_successful_run_emits_info_log(self):
        endpoint = self._create_hogql_endpoint("logs_ok", "SELECT 1")

        with mock.patch("products.endpoints.backend.api.log_endpoint_execution") as mock_log:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        self.assertEqual(kwargs["level"], "INFO")
        self.assertEqual(kwargs["log_source_id"], str(endpoint.id))
        self.assertTrue(kwargs["instance_id"])
        self.assertIn("Endpoint executed", kwargs["message"])
        self.assertIn("path=inline", kwargs["message"])
        self.assertIn("rows=1", kwargs["message"])
        self.assertIn("version=1", kwargs["message"])

    def test_failed_run_emits_error_log(self):
        endpoint = self._create_hogql_endpoint("logs_fail", "SELECT nonexistent_column_xyz FROM events")

        with mock.patch("products.endpoints.backend.api.log_endpoint_execution") as mock_log:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        self.assertEqual(kwargs["level"], "ERROR")
        self.assertEqual(kwargs["log_source_id"], str(endpoint.id))
        self.assertIn("Endpoint execution failed", kwargs["message"])
        self.assertIn("error=", kwargs["message"])

    def test_logs_action_returns_endpoint_entries(self):
        endpoint = self._create_hogql_endpoint("logs_read", "SELECT 1")
        create_log_entry(
            team_id=self.team.pk,
            log_source=ENDPOINTS_LOG_SOURCE,
            log_source_id=str(endpoint.id),
            instance_id="exec-1",
            message="Endpoint executed · path=inline cache=miss duration_ms=5 rows=1 version=1",
            level="info",
            timestamp="2026-01-01 12:00:00",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/logs/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["log_source_id"], str(endpoint.id))
        self.assertEqual(results[0]["instance_id"], "exec-1")
        self.assertEqual(results[0]["level"], "INFO")
        self.assertIn("path=inline", results[0]["message"])

    def test_logs_action_filters_by_level(self):
        endpoint = self._create_hogql_endpoint("logs_levels", "SELECT 1")
        for level in ("info", "error", "info"):
            create_log_entry(
                team_id=self.team.pk,
                log_source=ENDPOINTS_LOG_SOURCE,
                log_source_id=str(endpoint.id),
                instance_id="exec-1",
                message=f"msg {level}",
                level=level,
            )

        results = self.client.get(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/logs/", {"level": "ERROR"}
        ).json()["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["level"], "ERROR")
