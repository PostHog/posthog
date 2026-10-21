import json
from datetime import UTC, date, datetime
from typing import Any

import time_machine
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.perigon import (
    PerigonSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.perigon import (
    MAX_PAGE,
    PERIGON_BASE_URL,
    PerigonPaginator,
    PerigonResumeConfig,
    _clamp_future_value_to_now,
    _format_datetime,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.settings import PERIGON_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.source import PerigonSource


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _driver() -> SourceDriver:
    return SourceDriver(PerigonSource(), PerigonSourceConfig(api_key="key"))


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestClampFutureValueToNow:
    @parameterized.expand(
        [
            ("future_datetime", datetime(2027, 2, 5, tzinfo=UTC), datetime(2026, 6, 15, 12, tzinfo=UTC)),
            ("past_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)),
            ("non_iso_string_passthrough", "cursor", "cursor"),
            ("future_iso_string", "2030-01-01T00:00:00Z", datetime(2026, 6, 15, 12, tzinfo=UTC)),
        ]
    )
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_clamp(self, _name: str, value: Any, expected: Any) -> None:
        assert _clamp_future_value_to_now(value) == expected


class TestPaginator:
    def _paginator(self, logger: MagicMock | None = None) -> PerigonPaginator:
        paginator = PerigonPaginator(page_size=2, endpoint="articles", logger=logger)
        request = MagicMock()
        request.params = {}
        paginator.init_request(request)
        assert request.params == {"page": 0}
        return paginator

    @parameterized.expand([("short_page", [{"a": 1}]), ("empty_page", [])])
    def test_short_or_empty_page_terminates(self, _name: str, data: list[dict[str, Any]]) -> None:
        paginator = self._paginator()
        paginator.update_state(_response({"articles": []}), data)
        assert paginator.has_next_page is False

    def test_depth_cap_stops_and_logs(self) -> None:
        # Perigon rejects pagination past its 10,000-row search window; running past the cap
        # would fail every large sync mid-way.
        logger = MagicMock()
        paginator = self._paginator(logger)
        paginator.page = MAX_PAGE
        paginator.update_state(_response({"articles": []}), [{"a": 1}, {"a": 2}])
        assert paginator.has_next_page is False
        logger.warning.assert_called_once()


class TestEndpointRequests:
    @parameterized.expand([(name, cfg.data_selector) for name, cfg in PERIGON_ENDPOINTS.items()])
    def test_rows_extracted_from_wrapper(self, endpoint: str, selector: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={selector: [{"k": "v"}]})])

        assert result.raised is None
        assert result.rows == [{"k": "v"}]
        assert result.requests[0].url.startswith(f"{PERIGON_BASE_URL}{PERIGON_ENDPOINTS[endpoint].path}?")
        assert result.params("page") == ["0"]
        assert result.params("size") == ["100"]

    def test_missing_wrapper_key_fails_loud(self) -> None:
        # A 200 body without the expected wrapper key means the response shape changed —
        # fail loud, not 0 rows.
        result = _driver().run("articles", [ScriptedResponse(json={"unexpected": []})])

        assert isinstance(result.raised, ValueError)

    def test_pagination_walks_pages_until_short_page(self) -> None:
        full_page = [{"articleId": str(i)} for i in range(100)]
        result = _driver().run(
            "articles",
            [ScriptedResponse(json={"articles": full_page}), ScriptedResponse(json={"articles": [{"articleId": "x"}]})],
        )

        assert result.raised is None
        assert len(result.rows) == 101
        assert result.params("page") == ["0", "1"]


class TestIncrementalParams:
    @parameterized.expand(
        [
            ("articles", "from", "reverseDate"),
            ("stories", "updatedFrom", "updatedAt"),
        ]
    )
    def test_watermark_passed_as_server_side_filter(self, endpoint: str, param: str, sort_by: str) -> None:
        selector = PERIGON_ENDPOINTS[endpoint].data_selector
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={selector: []})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param(param) == "2026-03-04T02:58:14Z"
        assert result.requests[0].param("sortBy") == sort_by


class TestResume:
    def test_resume_starts_from_saved_page(self) -> None:
        result = _driver().run(
            "articles", [ScriptedResponse(json={"articles": []})], resume_state=PerigonResumeConfig(page=7)
        )

        assert result.raised is None
        assert result.params("page") == ["7"]


class TestPerigonSourceResponse:
    @parameterized.expand([(name,) for name in PERIGON_ENDPOINTS])
    def test_primary_keys_and_sort_mode_match_config(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={PERIGON_ENDPOINTS[endpoint].data_selector: []})])
        response = result.response
        config = PERIGON_ENDPOINTS[endpoint]
        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
