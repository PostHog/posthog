from typing import Any, Literal, cast

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.segment import (
    SegmentSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment import (
    SegmentResumeConfig,
    _base_url,
    _extract_rows,
    _next_cursor,
    _redact_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.settings import SEGMENT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.source import SegmentSource


def _driver(region: str = "api") -> SourceDriver:
    return SourceDriver(
        SegmentSource(), SegmentSourceConfig(api_token="tok", region=cast(Literal["api", "eu1"], region))
    )


def _page(body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "api", "https://api.segmentapis.com"),
            ("eu", "eu1", "https://eu1.api.segmentapis.com"),
            # An unknown region falls back to the US host rather than building a broken URL.
            ("unknown", "mars", "https://api.segmentapis.com"),
        ]
    )
    def test_base_url(self, _name: str, region: str, expected: str) -> None:
        assert _base_url(region) == expected


class TestExtractRows:
    @parameterized.expand(
        [
            ("sources_key", {"data": {"sources": [{"id": "s1"}], "pagination": {}}}, [{"id": "s1"}]),
            # The array key isn't always the endpoint name: audit-events returns it under "events".
            ("events_key", {"data": {"events": [{"id": "e1"}], "pagination": {}}}, [{"id": "e1"}]),
            ("labels_key", {"data": {"labels": [{"key": "env", "value": "dev"}]}}, [{"key": "env", "value": "dev"}]),
            ("empty_list", {"data": {"sources": [], "pagination": {}}}, []),
            ("no_data", {}, []),
            ("data_not_dict", {"data": []}, []),
        ]
    )
    def test_extract_rows(self, _name: str, body: dict[str, Any], expected: list[dict[str, Any]]) -> None:
        assert _extract_rows(body) == expected

    def test_pagination_object_is_never_returned_as_rows(self) -> None:
        # `pagination` is a dict, not a list, so it must not be mistaken for the resource array.
        body = {"data": {"pagination": {"next": "x"}, "sources": [{"id": "s1"}]}}
        assert _extract_rows(body) == [{"id": "s1"}]


class TestRedactRows:
    def test_no_redacted_fields_returns_rows_unchanged(self) -> None:
        rows = [{"id": "1", "settings": {"k": "v"}}]
        assert _redact_rows(rows, frozenset()) == rows


class TestNextCursor:
    @parameterized.expand(
        [
            ("has_next", {"data": {"pagination": {"next": "Mw=="}}}, "Mw=="),
            ("next_null", {"data": {"pagination": {"next": None}}}, None),
            ("next_empty", {"data": {"pagination": {"next": ""}}}, None),
            ("no_pagination", {"data": {"sources": []}}, None),
            ("no_data", {}, None),
        ]
    )
    def test_next_cursor(self, _name: str, body: dict[str, Any], expected: str | None) -> None:
        assert _next_cursor(body) == expected


class TestGetRows:
    def test_paginates_until_next_is_absent(self) -> None:
        result = _driver().run(
            "sources",
            [
                _page({"data": {"sources": [{"id": "s1"}], "pagination": {"next": "c1"}}}),
                _page({"data": {"sources": [{"id": "s2"}], "pagination": {"next": "c2"}}}),
                _page({"data": {"sources": [{"id": "s3"}], "pagination": {"next": None}}}),
            ],
        )
        assert result.rows == [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]
        assert result.params("pagination[cursor]") == [None, "c1", "c2"]
        assert result.saved_states == [SegmentResumeConfig(cursor="c1"), SegmentResumeConfig(cursor="c2")]

    def test_resume_starts_from_saved_cursor(self) -> None:
        result = _driver().run(
            "sources",
            [_page({"data": {"sources": [{"id": "s9"}], "pagination": {"next": None}}})],
            resume_state=SegmentResumeConfig(cursor="resumed"),
        )

        assert result.rows == [{"id": "s9"}]
        assert result.requests[0].param("pagination[cursor]") == "resumed"

    def test_credential_fields_are_redacted(self) -> None:
        # Credential-like config must never reach the queryable warehouse table.
        cases = [
            ("destinations", {"id": "d1", "settings": {"apiKey": "secret"}}, {"id": "d1"}),
            ("warehouses", {"id": "w1", "settings": {"password": "secret"}}, {"id": "w1"}),
            ("sources", {"id": "s1", "writeKeys": ["wk_secret"]}, {"id": "s1"}),
        ]
        for endpoint, raw_row, expected_row in cases:
            result = _driver().run(endpoint, [_page({"data": {endpoint: [raw_row], "pagination": {"next": None}}})])
            assert result.rows == [expected_row], endpoint

    def test_single_object_endpoint_yields_one_row_and_no_pagination(self) -> None:
        result = _driver().run(
            "workspace", [_page({"data": {"workspace": {"id": "w1", "name": "Acme", "slug": "acme"}}})]
        )

        assert result.rows == [{"id": "w1", "name": "Acme", "slug": "acme"}]
        # The workspace endpoint hits its bare path once, with no pagination params.
        assert result.urls == ["https://api.segmentapis.com/"]
        assert result.saved_states == []


class TestSegmentSource:
    @staticmethod
    def _empty_page(_request: Any) -> ScriptedResponse:
        return _page({"data": {"pagination": {}}})

    @parameterized.expand([(name,) for name in SEGMENT_ENDPOINTS])
    def test_source_response_carries_endpoint_primary_keys(self, endpoint: str) -> None:
        result = _driver().run(endpoint, self._empty_page)

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == SEGMENT_ENDPOINTS[endpoint].primary_keys

    @parameterized.expand(
        [
            ("audit_events_partitions_on_timestamp", "audit_events", "datetime", ["timestamp"]),
            ("sources_unpartitioned", "sources", None, None),
        ]
    )
    def test_partitioning(
        self, _name: str, endpoint: str, expected_mode: str | None, expected_keys: list[str] | None
    ) -> None:
        result = _driver().run(endpoint, self._empty_page)

        assert result.response is not None
        assert result.response.partition_mode == expected_mode
        assert result.response.partition_keys == expected_keys
