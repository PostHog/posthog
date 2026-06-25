from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_log_entries import create_log_entry
from posthog.models import Team

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
                {"succeeded": True, "execution_type": "inline", "version": 1},
                "Endpoint executed · path=inline version=1",
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

        with mock.patch("products.endpoints.backend.services.execution.log_endpoint_execution") as mock_log:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        self.assertEqual(kwargs["level"], "INFO")
        self.assertEqual(kwargs["endpoint_id"], str(endpoint.id))
        self.assertTrue(kwargs["instance_id"])
        self.assertIn("Endpoint executed", kwargs["message"])
        self.assertIn("path=inline", kwargs["message"])
        self.assertIn("rows=1", kwargs["message"])
        self.assertIn("version=1", kwargs["message"])

    def test_failed_run_emits_error_log(self):
        endpoint = self._create_hogql_endpoint("logs_fail", "SELECT nonexistent_column_xyz FROM events")

        with mock.patch("products.endpoints.backend.services.execution.log_endpoint_execution") as mock_log:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        self.assertEqual(kwargs["level"], "ERROR")
        self.assertEqual(kwargs["endpoint_id"], str(endpoint.id))
        self.assertIn("Endpoint execution failed", kwargs["message"])
        self.assertIn("error=", kwargs["message"])

    def test_successful_run_returns_execution_id_matching_log(self):
        endpoint = self._create_hogql_endpoint("logs_exec_id", "SELECT 1")

        with mock.patch("products.endpoints.backend.services.execution.log_endpoint_execution") as mock_log:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", {}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        execution_id = response.json()["execution_id"]
        self.assertTrue(execution_id)
        # The id returned to the client must be the same one written to the logs, so it can be traced.
        self.assertEqual(execution_id, mock_log.call_args.kwargs["instance_id"])

    def test_invalid_refresh_mode_emits_error_log_and_clean_message(self):
        endpoint = self._create_hogql_endpoint("logs_bad_refresh", "SELECT 1")

        with mock.patch("products.endpoints.backend.services.execution.log_endpoint_execution") as mock_log:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"refresh": "hey"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # A rejected request must still surface as a failed execution in the logs.
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        self.assertEqual(kwargs["level"], "ERROR")
        self.assertEqual(kwargs["endpoint_id"], str(endpoint.id))
        self.assertIn("Endpoint execution failed", kwargs["message"])

        # The customer-facing error must be clean — no pydantic internals leaking through.
        body = response.json()
        serialized = str(body)
        self.assertNotIn("errors.pydantic.dev", serialized)
        self.assertNotIn("JSON parse error", serialized)
        self.assertIn("refresh", serialized)
        self.assertIn("cache", serialized)

    @parameterized.expand(
        [
            ("invalid_limit", {"limit": 0}, status.HTTP_400_BAD_REQUEST),
            ("offset_without_limit", {"offset": 5}, status.HTTP_400_BAD_REQUEST),
            ("version_not_found", {"version": 999}, status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_rejected_run_params_emit_error_log(self, _name, body, expected_status):
        # Version/limit/offset parsing returns a 4xx Response instead of raising, but the rejection
        # must still surface in the logs.
        endpoint = self._create_hogql_endpoint(f"logs_reject_{_name}", "SELECT 1")

        with mock.patch("products.endpoints.backend.services.execution.log_endpoint_execution") as mock_log:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/", body, format="json"
            )

        self.assertEqual(response.status_code, expected_status)
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        self.assertEqual(kwargs["level"], "ERROR")
        self.assertEqual(kwargs["endpoint_id"], str(endpoint.id))
        self.assertIn("Endpoint execution failed", kwargs["message"])

    def test_validate_run_request_failure_emits_error_log(self):
        # `direct` refresh is valid per the schema but rejected by validate_run_request for a
        # non-materialized endpoint — this failure must still surface in the logs.
        endpoint = self._create_hogql_endpoint("logs_bad_validate", "SELECT 1")

        with mock.patch("products.endpoints.backend.services.execution.log_endpoint_execution") as mock_log:
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/run/",
                {"refresh": "direct"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        self.assertEqual(kwargs["level"], "ERROR")
        self.assertEqual(kwargs["endpoint_id"], str(endpoint.id))
        self.assertIn("Endpoint execution failed", kwargs["message"])
        self.assertIn("refresh", kwargs["message"])

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

    def test_logs_action_isolated_across_teams(self):
        other_team = Team.objects.create(organization=self.organization)
        other_endpoint = create_endpoint_with_version(
            name="other_team_endpoint",
            team=other_team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
        )
        # The other team's endpoint has logs, but they must be unreachable from our team's context.
        create_log_entry(
            team_id=other_team.pk,
            log_source=ENDPOINTS_LOG_SOURCE,
            log_source_id=str(other_endpoint.id),
            instance_id="exec-1",
            message="Endpoint executed · path=inline",
            level="info",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{other_endpoint.name}/logs/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_logs_action_rejects_invalid_limit(self):
        endpoint = self._create_hogql_endpoint("logs_bad_limit", "SELECT 1")

        response = self.client.get(f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/logs/", {"limit": 999})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
