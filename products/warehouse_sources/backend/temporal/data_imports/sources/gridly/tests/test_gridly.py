import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gridly import GridlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.gridly import (
    MAX_RETRY_ATTEMPTS,
    GridlyResumeConfig,
    GridlyRetryableError,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.settings import ENDPOINTS, GRIDLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.source import GridlySource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gridly.gridly"


def _driver() -> SourceDriver:
    return SourceDriver(GridlySource(), GridlySourceConfig(api_key="key", view_id="view"))


def _records_response(records: list[dict[str, Any]], total: int | None) -> ScriptedResponse:
    headers = {} if total is None else {"X-Total-Count": str(total)}
    return ScriptedResponse(json=records, headers=headers)


class TestRecordsPagination:
    @patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_paginates_by_offset_and_yields_raw_records(self) -> None:
        result = _driver().run(
            "records",
            [
                _records_response([{"id": "1"}, {"id": "2"}], total=3),
                _records_response([{"id": "3"}], total=3),
            ],
        )

        # Rows are yielded one page (list) at a time in the shape the API returns them.
        assert result.raised is None
        assert result.items == [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]

        # The `page` param is a JSON blob with offset advancing by the page length.
        assert [json.loads(page) for page in result.params("page") if page is not None] == [
            {"offset": 0, "limit": 2},
            {"offset": 2, "limit": 2},
        ]
        assert result.saved_states == [GridlyResumeConfig(offset=2)]

    @patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_stops_on_short_page_without_total(self) -> None:
        # A short page (fewer than the page size) terminates even when X-Total-Count is absent.
        result = _driver().run("records", [_records_response([{"id": "1"}], total=None)])

        assert result.raised is None
        assert result.items == [[{"id": "1"}]]
        assert len(result.requests) == 1

    @patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("records", [_records_response([], total=10)], resume_state=GridlyResumeConfig(offset=4))

        assert result.raised is None
        assert json.loads(result.requests[0].param("page") or "null")["offset"] == 4


class TestColumns:
    def test_reads_columns_from_view_object(self) -> None:
        result = _driver().run(
            "columns",
            [ScriptedResponse(json={"id": "view", "name": "Food", "columns": [{"id": "c1"}, {"id": "c2"}]})],
        )

        assert result.raised is None
        assert result.items == [[{"id": "c1"}, {"id": "c2"}]]
        assert result.paths == ["/v1/views/view"]


_HIERARCHY_RESPONSES: dict[tuple[str, tuple[tuple[str, str], ...]], list[dict[str, Any]]] = {
    ("/v1/projects", ()): [{"id": 1, "name": "P1"}, {"id": 2, "name": "P2"}],
    ("/v1/databases", (("projectId", "1"),)): [{"id": "db1", "name": "D1"}],
    ("/v1/databases", (("projectId", "2"),)): [],
    ("/v1/grids", (("dbId", "db1"),)): [{"id": "g1", "name": "G1"}, {"id": "g2", "name": "G2"}],
    ("/v1/views", (("gridId", "g1"),)): [{"id": "v1", "name": "Default view"}],
    ("/v1/views", (("gridId", "g2"),)): [{"id": "v2", "name": "Default view"}, {"id": "v3", "name": "Fr"}],
    ("/v1/branches", (("gridId", "g1"),)): [],
    ("/v1/branches", (("gridId", "g2"),)): [{"id": "b1", "name": "Summer"}],
}


def _hierarchy_response(request: RecordedRequest) -> ScriptedResponse:
    params = tuple((key, value) for key in ("projectId", "dbId", "gridId") if (value := request.param(key)) is not None)
    return ScriptedResponse(json=_HIERARCHY_RESPONSES[(request.path, params)])


class TestHierarchy:
    @pytest.mark.parametrize(
        "endpoint, expected_batches",
        [
            ("projects", [[{"id": 1, "name": "P1"}, {"id": 2, "name": "P2"}]]),
            ("databases", [[{"id": "db1", "name": "D1", "projectId": 1}]]),
            (
                "grids",
                [[{"id": "g1", "name": "G1", "dbId": "db1"}, {"id": "g2", "name": "G2", "dbId": "db1"}]],
            ),
            (
                "views",
                [
                    [{"id": "v1", "name": "Default view", "gridId": "g1"}],
                    [{"id": "v2", "name": "Default view", "gridId": "g2"}, {"id": "v3", "name": "Fr", "gridId": "g2"}],
                ],
            ),
            ("branches", [[{"id": "b1", "name": "Summer", "gridId": "g2"}]]),
        ],
    )
    def test_walks_hierarchy_and_tags_rows_with_parent_id(
        self, endpoint: str, expected_batches: list[list[dict[str, Any]]]
    ) -> None:
        result = _driver().run(endpoint, _hierarchy_response)

        assert result.raised is None
        assert result.items == expected_batches


class TestDependencies:
    def test_reads_dependencies_of_the_view(self) -> None:
        dependencies = [{"id": "d1", "sourceColumnId": "enUS", "targetColumnId": "frFR"}]
        result = _driver().run("dependencies", [ScriptedResponse(json=dependencies)])

        assert result.raised is None
        assert result.items == [dependencies]
        assert result.paths == ["/v1/views/view/dependencies"]


_EXECUTIONS: dict[str, list[dict[str, Any]]] = {
    "/v1/automations/a1/executions": [{"id": "e1", "status": "SUCCESS"}, {"id": "e2", "status": "FAILED"}],
    "/v1/automations/a2/executions": [],
    "/v1/automations/a3/executions": [{"id": "e1", "status": "STARTED"}],
}


def _automations_response(request: RecordedRequest) -> ScriptedResponse:
    if request.path == "/v1/automations":
        assert request.param("viewId") == "view"
        return ScriptedResponse(json=[{"id": "a1"}, {"id": "a2"}, {"id": "a3"}])
    return ScriptedResponse(json=_EXECUTIONS[request.path])


class TestAutomationExecutions:
    @pytest.mark.parametrize(
        "resume_offset, expected_items, expected_paths",
        [
            (
                None,
                [
                    [
                        {"id": "e1", "status": "SUCCESS", "automationId": "a1"},
                        {"id": "e2", "status": "FAILED", "automationId": "a1"},
                    ],
                    [{"id": "e1", "status": "STARTED", "automationId": "a3"}],
                ],
                [
                    "/v1/automations",
                    "/v1/automations/a1/executions",
                    "/v1/automations/a2/executions",
                    "/v1/automations/a3/executions",
                ],
            ),
            (
                2,
                [[{"id": "e1", "status": "STARTED", "automationId": "a3"}]],
                ["/v1/automations", "/v1/automations/a3/executions"],
            ),
        ],
    )
    def test_fans_out_over_automations_from_the_resume_position(
        self, resume_offset: int | None, expected_items: list[list[dict[str, Any]]], expected_paths: list[str]
    ) -> None:
        resume_state = None if resume_offset is None else GridlyResumeConfig(offset=resume_offset)
        result = _driver().run("automation_executions", _automations_response, resume_state=resume_state)

        assert result.raised is None
        assert result.items == expected_items
        assert result.paths == expected_paths


_RECORD_PAGES: dict[int, list[dict[str, Any]]] = {0: [{"id": "r1"}, {"id": "r2"}], 2: [{"id": "r3"}]}
_HISTORY_PAGES: dict[tuple[str, int], list[dict[str, Any]]] = {
    ("r1", 0): [{"lastModifiedTime": "t1"}, {"lastModifiedTime": "t2"}],
    ("r1", 2): [{"lastModifiedTime": "t3"}],
    ("r2", 0): [],
    ("r3", 0): [{"lastModifiedTime": "t4"}],
}


def _histories_response(request: RecordedRequest) -> ScriptedResponse:
    page = json.loads(request.param("page") or "null")
    assert page["limit"] == 2
    if request.path == "/v1/views/view/records":
        return ScriptedResponse(json=_RECORD_PAGES[page["offset"]])
    record_id = request.path.split("/")[-2]
    return ScriptedResponse(json=_HISTORY_PAGES[(record_id, page["offset"])])


class TestRecordHistories:
    @patch(f"{_MODULE}.PAGE_SIZE", 2)
    @pytest.mark.parametrize(
        "resume_offset, expected_items, expected_paths",
        [
            (
                None,
                [
                    [{"lastModifiedTime": "t1", "recordId": "r1"}, {"lastModifiedTime": "t2", "recordId": "r1"}],
                    [{"lastModifiedTime": "t3", "recordId": "r1"}],
                    [{"lastModifiedTime": "t4", "recordId": "r3"}],
                ],
                [
                    "/v1/views/view/records",
                    "/v1/views/view/records/r1/histories",
                    "/v1/views/view/records/r1/histories",
                    "/v1/views/view/records/r2/histories",
                    "/v1/views/view/records",
                    "/v1/views/view/records/r3/histories",
                ],
            ),
            (
                2,
                [[{"lastModifiedTime": "t4", "recordId": "r3"}]],
                ["/v1/views/view/records", "/v1/views/view/records/r3/histories"],
            ),
        ],
    )
    def test_walks_every_history_page_of_every_record_from_the_resume_position(
        self, resume_offset: int | None, expected_items: list[list[dict[str, Any]]], expected_paths: list[str]
    ) -> None:
        resume_state = None if resume_offset is None else GridlyResumeConfig(offset=resume_offset)
        result = _driver().run("record_histories", _histories_response, resume_state=resume_state)

        assert result.raised is None
        assert result.items == expected_items
        assert result.paths == expected_paths

    @patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_cursor_moves_past_a_record_only_with_its_last_history_page(self) -> None:
        result = _driver().run("record_histories", _histories_response)

        # r1 has two history pages: the cursor stays on r1 after its first page, at the second page,
        # and moves past r1 only with the second page.
        assert result.saved_states[0] == GridlyResumeConfig(offset=0, history_offset=2)
        assert result.saved_states[1] == GridlyResumeConfig(offset=1)
        assert GridlyResumeConfig(offset=2) in result.saved_states

    @patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_resumes_partway_through_the_history_of_a_record(self) -> None:
        result = _driver().run(
            "record_histories", _histories_response, resume_state=GridlyResumeConfig(offset=0, history_offset=2)
        )

        assert result.raised is None
        assert result.items[0] == [{"lastModifiedTime": "t3", "recordId": "r1"}]
        assert json.loads(result.requests[1].param("page") or "null")["offset"] == 2

    @patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_record_id_is_encoded_in_the_url_and_redacted_from_errors(self) -> None:
        record_id = "a/b?c#d"
        logger = MagicMock()

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/views/view/records":
                return ScriptedResponse(json=[{"id": record_id}])
            return ScriptedResponse(status=403)

        result = _driver().run("record_histories", respond, logger=logger)

        assert isinstance(result.raised, requests.HTTPError)
        assert "a%2Fb%3Fc%23d" in result.requests[1].url
        assert record_id not in str(result.raised)
        assert "a%2Fb" not in str(result.raised)
        assert "{recordId}/histories" in str(result.raised)
        assert "a%2Fb" not in " ".join(str(call) for call in logger.error.call_args_list)

    @patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_record_id_is_redacted_from_connection_errors(self) -> None:
        record_id = "secret@example.com"
        failure = requests.ConnectionError(
            f"Max retries exceeded with url: /v1/views/view/records/{record_id}/histories"
        )

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/views/view/records":
                return ScriptedResponse(json=[{"id": record_id}])
            raise failure

        result = _driver().run("record_histories", respond)

        assert isinstance(result.raised, requests.ConnectionError)
        assert record_id not in str(result.raised)
        assert "{recordId}/histories" in str(result.raised)


class TestRetries:
    def test_retries_exhausted_raises(self) -> None:
        result = _driver().run("records", always(ScriptedResponse(status=500)))

        assert isinstance(result.raised, GridlyRetryableError)
        assert len(result.requests) >= MAX_RETRY_ATTEMPTS
        assert set(result.paths) == {"/v1/views/view/records"}

    def test_client_error_is_not_retried(self) -> None:
        # A 401/403 can never be fixed by retrying, so it raises immediately (no retry loop).
        result = _driver().run("records", [ScriptedResponse(status=401)])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1

    def test_client_error_does_not_leak_response_body_or_query_string(self) -> None:
        # The error body echoes customer record content and the URL carries the `page` blob; neither
        # may reach the raised error (surfaced as latest_error) or the logs.
        secret_body = "secret customer record content"
        logger = MagicMock()
        result = _driver().run("records", [ScriptedResponse(status=401, body=secret_body.encode())], logger=logger)

        assert isinstance(result.raised, requests.HTTPError)
        raised = str(result.raised)
        assert secret_body not in raised
        assert "page=" not in raised
        assert raised == "401 Client Error: Unauthorized for url: https://api.gridly.com/v1/views/view/records"

        logged = " ".join(str(call) for call in logger.error.call_args_list)
        assert secret_body not in logged
        assert "page=" not in logged


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (404, False),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, message = validate_credentials("key", "view")

        assert is_valid is expected_valid
        assert (message is None) is expected_valid
        assert network.requests_log[0].path == "/v1/views/view"

    def test_swallows_exceptions(self) -> None:
        with scripted_network([Exception("boom")]):
            is_valid, message = validate_credentials("key", "view")

        assert is_valid is False
        assert message == "boom"


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        answer: dict[str, list[Any]] | list[Any] = {"columns": []} if endpoint == "columns" else []
        result = _driver().run(endpoint, always(ScriptedResponse(json=answer)))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == GRIDLY_ENDPOINTS[endpoint].primary_keys
        assert result.response.sort_mode == "asc"
        # No stable datetime on records → nothing to partition on.
        assert result.response.partition_keys is None
        assert result.response.partition_mode is None
