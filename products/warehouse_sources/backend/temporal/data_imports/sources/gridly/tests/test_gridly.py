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
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.settings import ENDPOINTS
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
        ],
    )
    def test_walks_hierarchy_and_tags_rows_with_parent_id(
        self, endpoint: str, expected_batches: list[list[dict[str, Any]]]
    ) -> None:
        result = _driver().run(endpoint, _hierarchy_response)

        assert result.raised is None
        assert result.items == expected_batches


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
            (200, True),
            (401, False),
            (403, False),
            (404, False),
            (500, False),
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
        assert result.response.primary_keys == ["id"]
        assert result.response.sort_mode == "asc"
        # No stable datetime on records → nothing to partition on.
        assert result.response.partition_keys is None
        assert result.response.partition_mode is None
