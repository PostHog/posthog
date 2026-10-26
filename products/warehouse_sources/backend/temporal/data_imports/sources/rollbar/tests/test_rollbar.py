from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rollbar import (
    RollbarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar import (
    KEYSET_PAGE_SIZE,
    UNREACHABLE_MESSAGE,
    RollbarResumeConfig,
    _extract_items,
    _to_int,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.settings import (
    ENDPOINTS,
    ROLLBAR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.source import RollbarSource


def _driver() -> SourceDriver:
    return SourceDriver(RollbarSource(), RollbarSourceConfig(access_token="token"))


def _response(data_key: str | None, items: list[dict[str, Any]]) -> ScriptedResponse:
    result: Any = items if data_key is None else {data_key: items}
    return ScriptedResponse(json={"err": 0, "result": result})


class TestToInt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (123, 123),
            ("123", 123),
            (123.9, 123),
            ("nope", None),
            (True, None),
        ],
    )
    def test_to_int_values(self, value, expected):
        assert _to_int(value) == expected


class TestExtractItems:
    def test_bare_list_result(self):
        # Defensive: a `result` that is itself a list is returned as-is regardless of data_key.
        assert _extract_items({"err": 0, "result": [{"id": 1}]}, "items") == [{"id": 1}]

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"err": 1, "message": "nope"},
            {"err": 0, "result": {"items": None}},
            {"err": 0, "result": None},
            "not-a-dict",
        ],
    )
    def test_missing_or_malformed_returns_empty(self, body):
        assert _extract_items(body, "items") == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (429, (False, UNREACHABLE_MESSAGE)),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected):
        with scripted_network(always(ScriptedResponse(status=status_code))):
            assert validate_credentials("token") == expected


class TestGetRowsPagePagination:
    def test_resumes_from_saved_page(self):
        result = _driver().run("deploys", [_response("deploys", [])], resume_state=RollbarResumeConfig(page=7))

        assert result.params("page") == ["7"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self):
        result = _driver().run("deploys", [_response("deploys", [])])

        assert result.params("page") == ["1"]

    def test_environments_keyed_result(self):
        result = _driver().run(
            "environments",
            [
                _response("environments", [{"id": 1, "environment": "production"}]),
                _response("environments", []),
            ],
        )

        assert result.items == [[{"id": 1, "environment": "production"}]]

    def test_pagination_ceiling_422_stops_after_first_page(self):
        # Rollbar rejects a page past an undocumented depth ceiling with a 422 instead of an
        # empty page. Once a page has already come back, that's end-of-data, not a failure.
        result = _driver().run(
            "items",
            [
                _response("items", [{"id": 1}]),
                ScriptedResponse(status=422),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": 1}]]

    def test_pagination_ceiling_422_on_first_page_propagates(self):
        # A 422 before any page has succeeded isn't a depth ceiling — Rollbar hasn't told us any
        # page works, so it must surface rather than being read as an empty sync.
        result = _driver().run("items", [ScriptedResponse(status=422)])

        assert isinstance(result.raised, requests.HTTPError)


class TestGetRowsKeyset:
    def test_walks_keyset_descending(self):
        first_page = [{"id": KEYSET_PAGE_SIZE * 2 - i} for i in range(KEYSET_PAGE_SIZE)]
        second_page = [{"id": 5}]

        result = _driver().run(
            "occurrences",
            [
                _response("instances", first_page),
                _response("instances", second_page),
            ],
        )

        assert len(result.items) == 2
        assert len(result.saved_states) == 1
        saved = result.saved_states[0]
        assert saved.last_id == min(item["id"] for item in first_page)
        assert result.params("lastId")[1] == str(saved.last_id)

    def test_incremental_stops_at_watermark(self):
        # Page contains rows above and below the watermark — only newer rows
        # are yielded and the walk stops.
        page = [{"id": 100 - i} for i in range(KEYSET_PAGE_SIZE)]

        result = _driver().run(
            "occurrences",
            [_response("instances", page)],
            incremental_field="id",
            db_incremental_field_last_value=50,
        )

        yielded_ids = [item["id"] for item in result.rows]
        assert yielded_ids == [100 - i for i in range(50)]
        assert len(result.requests) == 1

    def test_resumes_from_saved_last_id(self):
        result = _driver().run(
            "occurrences", [_response("instances", [])], resume_state=RollbarResumeConfig(last_id=12345)
        )

        assert result.params("lastId") == ["12345"]

    def test_a_run_with_no_saved_state_starts_from_the_head(self):
        result = _driver().run("occurrences", [_response("instances", [])])

        assert result.params("lastId") == [None]


class TestRollbarSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ROLLBAR_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, always(_response(config.data_key, [])))

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if config.pagination == "keyset":
            assert response.sort_mode == "desc"
        else:
            assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
