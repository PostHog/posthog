from datetime import date, datetime
from typing import Any

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crossref import crossref
from products.warehouse_sources.backend.temporal.data_imports.sources.crossref.crossref import (
    CrossrefResumeConfig,
    _build_params,
    _build_scope_filter,
    _format_filter_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crossref.source import CrossrefSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crossref import (
    CrossrefSourceConfig,
)


class _FakeBatcher:
    """Yields after every batched row, so pagination/cursor-save behaviour is deterministic
    without depending on the real Batcher's row/byte thresholds."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._buffer: list[dict] = []

    def batch(self, item: dict) -> None:
        self._buffer.append(item)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return bool(self._buffer)

    def get_table(self) -> pa.Table:
        table = pa.Table.from_pylist(self._buffer)
        self._buffer = []
        return table


def _page(items: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    message: dict[str, Any] = {"items": items}
    if next_cursor is not None:
        message["next-cursor"] = next_cursor
    return ScriptedResponse(json={"status": "ok", "message": message})


class TestBuildScopeFilter:
    @parameterized.expand(
        [
            ("member_only", "301", None, None, "member:301"),
            ("funder_only", None, "100000001", None, "funder:100000001"),
            ("issn_only", None, None, "1932-6203", "issn:1932-6203"),
            ("member_and_funder", "301", "100000001", None, "member:301,funder:100000001"),
            ("all_three", "301", "100000001", "1932-6203", "member:301,funder:100000001,issn:1932-6203"),
            ("none", None, None, None, None),
        ]
    )
    def test_build_scope_filter(self, _name, member_id, funder_id, issn, expected) -> None:
        assert _build_scope_filter(member_id, funder_id, issn) == expected


class TestFormatFilterValue:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "2026-03-04", "2026-03-04"),
        ]
    )
    def test_format_filter_value(self, _name, value, expected) -> None:
        assert _format_filter_value(value) == expected


class TestBuildParams:
    def test_works_incremental_with_watermark_adds_date_filter(self) -> None:
        params = _build_params(
            "Works",
            None,
            "301",
            None,
            None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1),
            incremental_field="indexed_date",
        )
        assert params["filter"] == "member:301,from-index-date:2024-01-01T00:00:00"
        assert params["sort"] == "indexed"

    def test_works_full_refresh_never_sorts_or_filters_by_date(self) -> None:
        params = _build_params(
            "Works",
            None,
            "301",
            None,
            None,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1),
            incremental_field="indexed_date",
        )
        assert "sort" not in params
        assert "order" not in params
        assert params["filter"] == "member:301"


class TestGetRowsCursorPagination:
    @staticmethod
    def _driver(mailto: str | None = None) -> SourceDriver:
        return SourceDriver(CrossrefSource(), CrossrefSourceConfig(mailto=mailto, member_id="301"))

    def test_stops_on_empty_items_page(self) -> None:
        result = self._driver().run("Works", [_page([{"DOI": "1"}], "c2"), _page([], "c3")])

        assert result.raised is None
        assert [row["DOI"] for row in result.rows[0].to_pylist()] == ["1"]
        assert result.params("cursor") == ["*", "c2"]

    def test_saves_state_only_while_next_cursor_present(self, monkeypatch) -> None:
        monkeypatch.setattr(crossref, "Batcher", _FakeBatcher)
        result = self._driver().run("Works", [_page([{"DOI": "1"}], "c2"), _page([{"DOI": "2"}])])

        assert result.raised is None
        assert result.saved_states == [CrossrefResumeConfig(cursor="c2")]
        assert result.committed_states == [CrossrefResumeConfig(cursor="c2")]
        assert result.final_state == CrossrefResumeConfig(cursor="c2")

    @parameterized.expand(
        [
            (
                "works_date",
                "Works",
                {"DOI": "1", "indexed": {"date-time": "2026-01-01T00:00:00Z"}},
                "indexed_date",
                "2026-01-01T00:00:00Z",
            ),
            (
                "journal_issns_sorted",
                "Journals",
                {"title": "J", "ISSN": ["1097-4547", "0360-4012"]},
                "issn_key",
                "0360-4012,1097-4547",
            ),
            ("journal_without_issn", "Journals", {"title": "J", "ISSN": []}, "issn_key", ""),
        ]
    )
    def test_rows_are_normalized(self, _name, endpoint, item, column, expected) -> None:
        result = self._driver().run(endpoint, [_page([item])])

        assert result.raised is None
        assert result.rows[0].to_pylist()[0][column] == expected

    def test_mailto_passed_as_redact_value(self) -> None:
        """mailto is a user-typed contact email, not a secret, but it should still be kept out
        of logged/captured request URLs like other tracked-session redactions."""
        result = self._driver("me@example.com").run("Works", [_page([{"DOI": "1"}])])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("me@example.com",)

    def test_no_mailto_passes_no_redact_values(self) -> None:
        result = self._driver().run("Works", [_page([{"DOI": "1"}])])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ()


class TestGetRowsTypesEndpoint:
    def test_single_request_with_no_cursor(self) -> None:
        result = SourceDriver(CrossrefSource(), CrossrefSourceConfig()).run(
            "Types", [_page([{"id": "journal-article", "label": "Journal Article"}])]
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows[0].to_pylist()] == ["journal-article"]
        assert result.paths == ["/types"]
        assert result.params("cursor") == [None]


class TestCrossrefSourceResponse:
    def test_members_response_has_no_partitioning(self) -> None:
        result = SourceDriver(CrossrefSource(), CrossrefSourceConfig()).run("Members", [_page([])])
        response = result.response
        assert result.raised is None
        assert response is not None
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    def test_swallows_transport_errors(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials(None) is False
        assert {request.path for request in network.requests_log} == {"/works"}

    def test_mailto_included_in_request(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("me@example.com") is True

        assert network.requests_log[0].param("mailto") == "me@example.com"

    def test_mailto_passed_as_redact_value(self) -> None:
        """mailto is a user-typed contact email, not a secret, but it should still be kept out
        of logged/captured request URLs like other tracked-session redactions."""
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("me@example.com") is True

        assert network.session_options[0]["redact_values"] == ("me@example.com",)

    def test_no_mailto_passes_no_redact_values(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials(None) is True

        assert network.session_options[0]["redact_values"] == ()
