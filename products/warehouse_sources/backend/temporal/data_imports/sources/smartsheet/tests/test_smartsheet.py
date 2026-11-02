from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartsheet import (
    SmartsheetSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import (
    ENDPOINTS,
    EVENTS_MAX_COUNT,
    PAGE_SIZE,
    ROWS_PAGE_SIZE,
    SMARTSHEET_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet import (
    SmartsheetResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.source import SmartsheetSource


def _response(items: list[dict[str, Any]], total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={"pageNumber": 1, "pageSize": PAGE_SIZE, "totalPages": total_pages, "data": items},
    )


def _run(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(SmartsheetSource(), SmartsheetSourceConfig(access_token="token")).run(
        endpoint, script, **inputs
    )


class TestPagination:
    def test_paginates_through_total_pages(self) -> None:
        result = _run(
            "sheets", [_response([{"id": 1}, {"id": 2}], total_pages=2), _response([{"id": 3}], total_pages=2)]
        )

        assert [r["id"] for r in result.rows] == [1, 2, 3]
        # Each request asks for an explicit ascending page number plus the fixed page size.
        assert result.params("page") == ["1", "2"]
        assert result.requests[0].param("pageSize") == str(PAGE_SIZE)
        # State is saved once — only while a further page remains — pointing at the next page.
        assert result.saved_states == [SmartsheetResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _run(
            "sheets",
            [_response([{"id": 9}], total_pages=3)],
            resume_state=SmartsheetResumeConfig(next_page=3),
        )

        assert result.params("page")[0] == "3"


def _sheets(*sheet_ids: int) -> ScriptedResponse:
    return _response([{"id": sheet_id} for sheet_id in sheet_ids], total_pages=1)


def _rows(first_id: int, count: int, total_row_count: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "id": 1,
            "totalRowCount": total_row_count,
            "columns": [{"id": 7, "title": "Status"}],
            "rows": [{"id": first_id + i, "cells": [{"columnId": 7, "value": "Open"}]} for i in range(count)],
        }
    )


def _events(event_ids: list[str], next_position: str, more_available: bool) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "nextStreamPosition": next_position,
            "moreAvailable": more_available,
            "data": [{"eventId": event_id, "eventTimestamp": "2026-03-02T10:00:00Z"} for event_id in event_ids],
        }
    )


class TestSheetRows:
    @pytest.mark.parametrize(
        "row_pages, expected_pages",
        [
            # A short page is the last one.
            ([_rows(1, ROWS_PAGE_SIZE, 600), _rows(501, 100, 600)], ["1", "2"]),
            # A full page that reaches totalRowCount is the last one; asking for page 2 would make
            # Smartsheet return page 1 again.
            ([_rows(1, ROWS_PAGE_SIZE, ROWS_PAGE_SIZE)], ["1"]),
            # No totalRowCount means no safe way to know a next page exists.
            ([ScriptedResponse(json={"rows": [{"id": i} for i in range(ROWS_PAGE_SIZE)]})], ["1"]),
        ],
    )
    def test_full_refresh_pages_rows_until_the_row_count(
        self, row_pages: list[ScriptedResponse], expected_pages: list[str]
    ) -> None:
        result = _run("sheet_rows", route({"/sheets": [_sheets(11)], "/sheets/11": row_pages}))

        assert result.raised is None
        row_requests = [r for r in result.requests if r.path.endswith("/sheets/11")]
        assert [r.param("page") for r in row_requests] == expected_pages
        assert {r.param("pageSize") for r in row_requests} == {str(ROWS_PAGE_SIZE)}
        assert all(r.param("rowsModifiedSince") is None for r in row_requests)
        assert {row["sheetId"] for row in result.rows} == {11}

    @pytest.mark.parametrize(
        "last_value",
        [datetime(2026, 3, 1, 12, 30, tzinfo=UTC), "2026-03-01T12:30:00Z", "2026-03-01T13:30:00+01:00"],
    )
    def test_incremental_reads_modified_rows_of_each_sheet_in_one_request(self, last_value: Any) -> None:
        result = _run(
            "sheet_rows",
            route(
                {
                    "/sheets": [_sheets(11, 12)],
                    # A full page with a larger totalRowCount must not ask for page 2 once filtered.
                    "/sheets/11": [_rows(1, ROWS_PAGE_SIZE, 5000)],
                    "/sheets/12": [_rows(9001, 2, 5000)],
                }
            ),
            incremental_field="modifiedAt",
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        row_requests = [r for r in result.requests if "/sheets/1" in r.path]
        assert [r.path.rsplit("/", 1)[-1] for r in row_requests] == ["11", "12"]
        for request in row_requests:
            assert request.param("rowsModifiedSince") == "2026-03-01T12:30:00Z"
            assert request.param("page") is None
            assert request.param("pageSize") is None
        assert len(result.rows) == ROWS_PAGE_SIZE + 2
        assert result.response is not None
        assert result.response.sort_mode == "desc"


class TestFanOutChildren:
    @pytest.mark.parametrize(
        "endpoint, script, parent_key, expected_rows",
        [
            (
                "sheet_columns",
                {
                    "/sheets": [_sheets(11)],
                    "/sheets/11/columns": [
                        _response([{"id": 7, "options": ["Open", "Done"]}], total_pages=2),
                        _response([{"id": 8}], total_pages=2),
                    ],
                },
                "sheetId",
                [(11, 7), (11, 8)],
            ),
            (
                "group_members",
                {
                    "/groups": [_response([{"id": 21}, {"id": 22}], total_pages=1)],
                    "/groups/21": [ScriptedResponse(json={"id": 21, "name": "Ops", "members": [{"id": 5}]})],
                    "/groups/22": [ScriptedResponse(json={"id": 22, "name": "Eng", "members": [{"id": 5}, {"id": 6}]})],
                },
                "groupId",
                [(21, 5), (22, 5), (22, 6)],
            ),
        ],
    )
    def test_child_rows_carry_their_parent_id(
        self,
        endpoint: str,
        script: dict[str, list[ScriptedResponse]],
        parent_key: str,
        expected_rows: list[tuple[int, int]],
    ) -> None:
        result = _run(endpoint, route(script))

        assert result.raised is None
        assert [(row[parent_key], row["id"]) for row in result.rows] == expected_rows


class TestEvents:
    @pytest.mark.parametrize(
        "inputs, expected_since",
        [
            ({}, "2000-01-01T00:00:00Z"),
            (
                {"incremental_field": "eventTimestamp", "db_incremental_field_last_value": "2026-03-02T10:20:00Z"},
                "2026-03-02T09:20:00Z",
            ),
        ],
    )
    def test_walks_the_stream_until_no_more_events(self, inputs: dict[str, Any], expected_since: str) -> None:
        result = _run(
            "events",
            [
                _events(["a", "b"], next_position="pos-2", more_available=True),
                # The stream always returns a next position; moreAvailable=false ends the walk.
                _events(["c"], next_position="pos-3", more_available=False),
            ],
            **inputs,
        )

        assert result.raised is None
        assert [row["eventId"] for row in result.rows] == ["a", "b", "c"]
        # The API takes exactly one of `since` and `streamPosition`.
        assert result.params("since") == [expected_since, None]
        assert result.params("streamPosition") == [None, "pos-2"]
        assert result.params("maxCount") == [str(EVENTS_MAX_COUNT)] * 2
        assert result.saved_states == [SmartsheetResumeConfig(stream_position="pos-2")]

    def test_resumes_from_saved_stream_position(self) -> None:
        result = _run(
            "events",
            [_events(["d"], next_position="pos-5", more_available=False)],
            resume_state=SmartsheetResumeConfig(stream_position="pos-4"),
        )

        assert result.raised is None
        assert result.params("streamPosition") == ["pos-4"]
        assert result.params("since") == [None]


class TestSmartsheetSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint) -> None:
        config = SMARTSHEET_ENDPOINTS[endpoint]
        response = _run(endpoint, always(_response([], total_pages=1))).response

        expected_keys = config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == ("desc" if config.incremental_fields else None)
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SMARTSHEET_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config) -> None:
        # Never partition on a mutable field like modifiedAt. An event's timestamp never changes.
        if config.partition_key:
            assert config.partition_key in ("createdAt", "eventTimestamp")


class TestValidateCredentials:
    def test_validate_credentials_probes_users_me(self) -> None:
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            validate_credentials("token")

        assert [request.url for request in network.requests_log] == ["https://api.smartsheet.com/2.0/users/me"]
        assert network.session_options[0]["redact_values"] == ("token",)
