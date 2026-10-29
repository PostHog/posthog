from typing import Any

from unittest import TestCase

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.testdino import (
    TestDinoSourceConfig as SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.settings import API_BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.source import TestDinoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.testdino import (
    TestDinoResumeConfig as ResumeConfig,
)


def response(body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body, headers=headers or {})


class TestDinoTransport(TestCase):
    def setUp(self) -> None:
        self.config = SourceConfig(personal_access_token="td_pat_fake_test_token", project_id="project_example")
        self.source = TestDinoSource()

    def run_table(
        self,
        name: str,
        script: Script,
        config: SourceConfig | None = None,
        resume_state: ResumeConfig | None = None,
    ) -> DriveResult:
        driver = SourceDriver(self.source, config or self.config)
        return driver.run(
            name, script, resume_state=resume_state, db_incremental_field_last_value="2026-01-01T00:00:00Z"
        )

    @parameterized.expand(
        [
            ("test_runs", "test-runs", False, {"limit": ("100",), "sort": ("counter_asc",)}),
            ("test_runs", "test-runs", True, {"limit": ("100",), "sort": ("counter_asc",)}),
            (
                "manual_runs",
                "manual-runs",
                False,
                {"limit": ("200",), "sortBy": ("createdAt",), "sortOrder": ("asc",)},
            ),
            (
                "manual_runs",
                "manual-runs",
                True,
                {"limit": ("200",), "sortBy": ("createdAt",), "sortOrder": ("asc",)},
            ),
        ]
    )
    def test_run_pages_and_resume(self, table: str, path: str, resume: bool, query: dict[str, tuple[str]]) -> None:
        initial_page = 3 if resume else 1
        pages = [
            response({"success": True, "data": [{"id": "run-a"}], "pagination": {"hasNext": True}}),
            response({"success": True, "data": [{"id": "run-b"}], "pagination": {"hasNext": False}}),
        ]
        result = self.run_table(table, pages, resume_state=ResumeConfig(page=3) if resume else None)

        self.assertIsNone(result.raised)
        self.assertEqual(result.items, [[{"id": "run-a"}], [{"id": "run-b"}]])
        self.assertEqual(result.saved_states, [ResumeConfig(page=initial_page + 1)])
        self.assertEqual(len(result.requests), 2)
        for offset, request in enumerate(result.requests):
            self.assertEqual(request.path, f"/api/v1/public/project_example/{path}")
            self.assertEqual(request.headers["authorization"], "Bearer td_pat_fake_test_token")
            self.assertEqual(request.query, {"page": (str(initial_page + offset),), **query})
        self.assertEqual(result.final_state, ResumeConfig(page=initial_page + 1))
        self.assertIsNone(result.completed_state)

    @parameterized.expand([(False,), (True,)])
    def test_empty_run_page_obeys_has_next(self, has_next: bool) -> None:
        pages = [response({"data": [], "pagination": {"hasNext": has_next}})]
        if has_next:
            pages.append(response({"data": [{"id": "run-a"}], "pagination": {"hasNext": False}}))
        result = self.run_table("test_runs", pages)

        self.assertEqual(result.rows, [{"id": "run-a"}] if has_next else [])
        self.assertEqual(len(result.requests), 2 if has_next else 1)
        if has_next:
            self.assertEqual(result.requests[-1].query["page"], ("2",))

    @parameterized.expand([(None,), ({},), ({"hasNext": "false"},)])
    def test_invalid_pagination_fails(self, pagination: dict[str, Any] | None) -> None:
        body: dict[str, Any] = {"data": [{"id": "run-a"}]}
        if pagination is not None:
            body["pagination"] = pagination
        result = self.run_table("test_runs", [response(body)])

        self.assertIsInstance(result.raised, RESTClientNonRetryableError)
        self.assertIn("pagination.hasNext", str(result.raised))
        self.assertEqual(result.saved_states, [])

    def test_manual_run_test_cases_fan_out(self) -> None:
        run_page = {"_id": "tcm_run_a", "name": "Smoke"}
        script = [
            response({"data": [run_page, {"_id": "tcm_run_deleted"}], "pagination": {"hasNext": True}}),
            response({"data": [{"caseKey": "TC-1", "status": "passed"}], "pagination": {"hasNext": True}}),
            response(
                {
                    "data": [{"caseKey": "TC-2", "status": "untested", "assignee": None}],
                    "pagination": {"hasNext": False},
                }
            ),
            response({"success": False, "error": {"code": "NOT_FOUND", "message": "Manual test run not found"}}, 404),
            response({"data": [{"_id": "tcm_run_empty"}], "pagination": {"hasNext": False}}),
            response({"data": [], "pagination": {"hasNext": False}}),
        ]
        result = self.run_table("manual_run_test_cases", script)

        self.assertIsNone(result.raised)
        self.assertEqual(
            result.rows,
            [
                {"caseKey": "TC-1", "status": "passed", "manual_run_id": "tcm_run_a"},
                {"caseKey": "TC-2", "status": "untested", "assignee": None, "manual_run_id": "tcm_run_a"},
            ],
        )
        assert result.response is not None
        self.assertEqual(result.response.primary_keys, ["manual_run_id", "caseKey"])
        self.assertEqual(
            [(request.path, request.query.get("page")) for request in result.requests],
            [
                ("/api/v1/public/project_example/manual-runs", ("1",)),
                ("/api/v1/public/project_example/manual-runs/tcm_run_a/test-cases", ("1",)),
                ("/api/v1/public/project_example/manual-runs/tcm_run_a/test-cases", ("2",)),
                ("/api/v1/public/project_example/manual-runs/tcm_run_deleted/test-cases", ("1",)),
                ("/api/v1/public/project_example/manual-runs", ("2",)),
                ("/api/v1/public/project_example/manual-runs/tcm_run_empty/test-cases", ("1",)),
            ],
        )
        child_queries = [request.query for request in result.requests if "test-cases" in request.path]
        self.assertEqual(
            child_queries,
            [
                {"page": (page,), "limit": ("200",), "sortBy": ("caseKey",), "sortOrder": ("asc",)}
                for page in ("1", "2", "1", "1")
            ],
        )

    @parameterized.expand(
        [
            ("manual_suites", "manual-test-suites", 0),
            ("manual_suites", "manual-test-suites", 2),
            ("manual_cases", "manual-test-cases", 0),
            ("manual_cases", "manual-test-cases", 999),
        ]
    )
    def test_single_page_tables(self, table: str, path: str, count: int) -> None:
        rows = [{"_id": f"record-{index}"} for index in range(count)]
        result = self.run_table(table, [response({"data": rows, "count": count})], resume_state=ResumeConfig(page=5))

        self.assertEqual(result.rows, rows)
        assert result.response is not None
        self.assertEqual(result.response.primary_keys, ["_id"])
        self.assertEqual(len(result.requests), 1)
        self.assertEqual(result.requests[0].path, f"/api/v1/public/project_example/{path}")
        self.assertEqual(result.queries[0], {"limit": ("1000",)} if table == "manual_cases" else {})

    def test_case_limit_fails_before_yielding(self) -> None:
        rows = [{"_id": f"case-{index}"} for index in range(1000)]
        result = self.run_table("manual_cases", [response({"data": rows, "count": 1000})])

        self.assertIsInstance(result.raised, RESTClientNonRetryableError)
        self.assertIn("1,000-case API limit", str(result.raised))
        self.assertEqual(result.rows, [])
        self.assertEqual(len(result.requests), 1)
        self.assertTrue(any(pattern in str(result.raised) for pattern in self.source.get_non_retryable_errors()))

    @parameterized.expand(
        [
            (400, "VALIDATION_ERROR", "Check the project ID"),
            (404, "NOT_FOUND", "projects allowed"),
        ]
    )
    def test_validation_and_error_mapping(self, status: int, code: str | None, expected: str | None) -> None:
        body = {"data": {"id": "token-example"}} if status == 200 else {"error": {"code": code}}
        with scripted_network([response(body, status)]) as network:
            valid, message = self.source.validate_credentials(self.config, team_id=1)
        self.assertEqual(len(network.requests_log), 1)
        request = network.requests_log[0]
        self.assertEqual(request.url, f"{API_BASE_URL}/project_example/token-info")
        self.assertEqual(request.headers["authorization"], "Bearer td_pat_fake_test_token")
        self.assertEqual(valid, status == 200)
        if expected is None:
            self.assertIsNone(message)
        else:
            self.assertIn(expected, message or "")
            result = self.run_table("test_runs", [response(body, status)])
            self.assertIsInstance(result.raised, HTTPError)
            messages = [
                value
                for pattern, value in self.source.get_non_retryable_errors().items()
                if pattern in str(result.raised)
            ]
            self.assertIn(message, messages)

    @parameterized.expand([(429,), (500,)])
    def test_transient_errors_retry(self, status: int) -> None:
        failure = response(
            {"error": {"code": "RATE_LIMIT_EXCEEDED" if status == 429 else "INTERNAL_ERROR"}},
            status,
            {"Retry-After": "0"},
        )
        success = response({"data": [], "pagination": {"hasNext": False}})
        result = self.run_table("test_runs", [failure, success])

        self.assertIsNone(result.raised)
        self.assertEqual(result.rows, [])
        self.assertEqual(len(result.requests), 2)

    @parameterized.expand(
        [("",), ("..",), ("../other",), ("example?query=1",), ("https://example.com",), ("project\n",)]
    )
    def test_invalid_project_never_sends_token(self, project_id: str) -> None:
        config = SourceConfig(personal_access_token="td_pat_fake_test_token", project_id=project_id)
        with scripted_network([]) as network:
            valid, message = self.source.validate_credentials(config, team_id=1)
            self.assertFalse(valid)
            self.assertIn("project ID", message or "")
            result = self.run_table("test_runs", [], config=config)
        self.assertIsInstance(result.raised, ValueError)
        self.assertIn("project ID", str(result.raised))
        self.assertEqual(network.requests_log, [])
        self.assertEqual(result.requests, [])
