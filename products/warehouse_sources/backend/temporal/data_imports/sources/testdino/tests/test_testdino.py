import json
from collections.abc import Iterable
from http.client import responses as status_names
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.testdino import (
    TestDinoSourceConfig as SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.settings import API_BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.source import TestDinoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.testdino import (
    TestDinoResumeConfig as ResumeConfig,
)


def response(body: dict[str, Any], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = status_names[status]
    result.url = f"{API_BASE_URL}/project_example/test-runs"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    return result


def source_items(source: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], source.items())


class TestDinoTransport(TestCase):
    def setUp(self) -> None:
        self.config = SourceConfig(personal_access_token="td_pat_fake_test_token", project_id="project_example")
        self.source = TestDinoSource()
        self.manager = MagicMock(spec=ResumableSourceManager)
        self.manager.can_resume.return_value = False

    def inputs(self, name: str) -> SourceInputs:
        return SourceInputs(
            schema_name=name,
            schema_id="schema-example",
            source_id="source-example",
            team_id=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id="job-example",
            logger=MagicMock(),
            reset_pipeline=False,
        )

    @parameterized.expand([(False,), (True,)])
    def test_run_pages_and_resume(self, resume: bool) -> None:
        self.manager.can_resume.return_value = resume
        self.manager.load_state.return_value = ResumeConfig(page=3)
        initial_page = 3 if resume else 1
        pages = [
            response({"success": True, "data": [{"id": "run-a"}], "pagination": {"hasNext": True}}),
            response({"success": True, "data": [{"id": "run-b"}], "pagination": {"hasNext": False}}),
        ]
        with (
            patch("requests.Session.send", side_effect=pages) as send,
            activate_safe_point(lambda: None, covers_framework_checkpoints=True),
        ):
            result = self.source.source_for_pipeline(self.config, self.manager, self.inputs("test_runs"))
            items = iter(source_items(result))
            self.assertEqual(next(items), [{"id": "run-a"}])
            self.manager.save_state.assert_called_once_with(ResumeConfig(page=initial_page + 1))
            self.assertEqual(list(items), [[{"id": "run-b"}]])

        self.assertEqual(send.call_count, 2)
        for offset, call in enumerate(send.call_args_list):
            request = call.args[0]
            self.assertEqual(urlsplit(request.url).path, "/api/v1/public/project_example/test-runs")
            self.assertEqual(request.headers["Authorization"], "Bearer td_pat_fake_test_token")
            self.assertEqual(
                parse_qs(urlsplit(request.url).query),
                {"page": [str(initial_page + offset)], "limit": ["100"], "sort": ["counter_asc"]},
            )
        self.manager.clear_state.assert_not_called()
        assert result.on_complete is not None
        result.on_complete()
        self.manager.clear_state.assert_called_once()

    @parameterized.expand([(False,), (True,)])
    def test_empty_run_page_obeys_has_next(self, has_next: bool) -> None:
        pages = [response({"data": [], "pagination": {"hasNext": has_next}})]
        if has_next:
            pages.append(response({"data": [{"id": "run-a"}], "pagination": {"hasNext": False}}))
        with patch("requests.Session.send", side_effect=pages) as send:
            result = self.source.source_for_pipeline(self.config, self.manager, self.inputs("test_runs"))
            rows = [row for page in source_items(result) for row in page]
        self.assertEqual(rows, [{"id": "run-a"}] if has_next else [])
        self.assertEqual(send.call_count, 2 if has_next else 1)
        if has_next:
            self.assertEqual(parse_qs(urlsplit(send.call_args.args[0].url).query)["page"], ["2"])

    @parameterized.expand([(None,), ({},), ({"hasNext": "false"},)])
    def test_invalid_pagination_fails(self, pagination: dict[str, Any] | None) -> None:
        body: dict[str, Any] = {"data": [{"id": "run-a"}]}
        if pagination is not None:
            body["pagination"] = pagination
        with patch("requests.Session.send", return_value=response(body)):
            result = self.source.source_for_pipeline(self.config, self.manager, self.inputs("test_runs"))
            with self.assertRaisesRegex(RESTClientNonRetryableError, "pagination.hasNext"):
                list(source_items(result))
        self.manager.save_state.assert_not_called()

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
        with patch("requests.Session.send", return_value=response({"data": rows, "count": count})) as send:
            result = self.source.source_for_pipeline(self.config, self.manager, self.inputs(table))
            self.assertEqual([row for page in source_items(result) for row in page], rows)
        self.assertEqual(result.primary_keys, ["_id"])
        send.assert_called_once()
        self.assertEqual(urlsplit(send.call_args.args[0].url).path, f"/api/v1/public/project_example/{path}")
        self.assertEqual(
            parse_qs(urlsplit(send.call_args.args[0].url).query), {"limit": ["1000"]} if table == "manual_cases" else {}
        )
        self.manager.can_resume.assert_not_called()

    def test_case_limit_fails_before_yielding(self) -> None:
        rows = [{"_id": f"case-{index}"} for index in range(1000)]
        with patch("requests.Session.send", return_value=response({"data": rows, "count": 1000})) as send:
            result = self.source.source_for_pipeline(self.config, self.manager, self.inputs("manual_cases"))
            with self.assertRaisesRegex(RESTClientNonRetryableError, "1,000-case API limit") as error:
                next(iter(source_items(result)))
        send.assert_called_once()
        self.assertTrue(any(pattern in str(error.exception) for pattern in self.source.get_non_retryable_errors()))

    @parameterized.expand(
        [
            (200, None, None),
            (400, "VALIDATION_ERROR", "Check the project ID"),
            (401, "UNAUTHORIZED", "Create a personal access token"),
            (401, "TOKEN_EXPIRED", "Create a personal access token"),
            (401, "TOKEN_REVOKED", "Create a personal access token"),
            (403, "FORBIDDEN", "projects allowed"),
            (404, "NOT_FOUND", "projects allowed"),
        ]
    )
    def test_validation_and_error_mapping(self, status: int, code: str | None, expected: str | None) -> None:
        body = {"data": {"id": "token-example"}} if status == 200 else {"error": {"code": code}}
        with patch("requests.Session.send", return_value=response(body, status)) as send:
            valid, message = self.source.validate_credentials(self.config, team_id=1)
        send.assert_called_once()
        request = send.call_args.args[0]
        self.assertEqual(request.url, f"{API_BASE_URL}/project_example/token-info")
        self.assertEqual(request.headers["Authorization"], "Bearer td_pat_fake_test_token")
        self.assertEqual(valid, status == 200)
        if expected is None:
            self.assertIsNone(message)
        else:
            self.assertIn(expected, message or "")
            with patch("requests.Session.send", return_value=response(body, status)):
                result = self.source.source_for_pipeline(self.config, self.manager, self.inputs("test_runs"))
                with self.assertRaises(HTTPError) as error:
                    list(source_items(result))
            messages = [
                value
                for pattern, value in self.source.get_non_retryable_errors().items()
                if pattern in str(error.exception)
            ]
            self.assertIn(message, messages)

    @parameterized.expand([(429,), (500,)])
    def test_transient_errors_retry(self, status: int) -> None:
        failure = response({"error": {"code": "RATE_LIMIT_EXCEEDED" if status == 429 else "INTERNAL_ERROR"}}, status)
        failure.headers["Retry-After"] = "0"
        success = response({"data": [], "pagination": {"hasNext": False}})
        with patch("requests.Session.send", side_effect=[failure, success]) as send:
            result = self.source.source_for_pipeline(self.config, self.manager, self.inputs("test_runs"))
            self.assertEqual(list(source_items(result)), [])
        self.assertEqual(send.call_count, 2)

    @parameterized.expand(
        [("",), ("..",), ("../other",), ("example?query=1",), ("https://example.com",), ("project\n",)]
    )
    def test_invalid_project_never_sends_token(self, project_id: str) -> None:
        config = SourceConfig(personal_access_token="td_pat_fake_test_token", project_id=project_id)
        with patch("requests.Session.send") as send:
            valid, message = self.source.validate_credentials(config, team_id=1)
            self.assertFalse(valid)
            self.assertIn("project ID", message or "")
            with self.assertRaisesRegex(ValueError, "project ID"):
                self.source.source_for_pipeline(config, self.manager, self.inputs("test_runs"))
        send.assert_not_called()

    def test_unknown_table_does_not_make_a_request(self) -> None:
        with patch("requests.Session.send") as send:
            with self.assertRaises(UnknownResourceError):
                self.source.source_for_pipeline(self.config, self.manager, self.inputs("unknown"))
        send.assert_not_called()
