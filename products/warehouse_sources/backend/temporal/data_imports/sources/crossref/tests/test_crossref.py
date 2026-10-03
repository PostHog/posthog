from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from unittest import mock

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.crossref import crossref
from products.warehouse_sources.backend.temporal.data_imports.sources.crossref.crossref import (
    CrossrefResumeConfig,
    _build_params,
    _build_scope_filter,
    _format_filter_value,
    _normalize_work,
    crossref_source,
    get_rows,
    validate_credentials,
)

CROSSREF_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.crossref.crossref.make_tracked_session"
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


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def _response(status_code: int, message: dict[str, Any] | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"status": "ok", "message": message or {}}
    resp.raise_for_status = mock.MagicMock()
    return resp


def _make_manager(resume_state: CrossrefResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _collect(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for table in get_rows(endpoint=endpoint, logger=mock.MagicMock(), resumable_source_manager=manager, **kwargs):
        rows.extend(table.to_pylist())
    return rows


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


class TestNormalizeWork:
    def test_flattens_nested_dates(self) -> None:
        item = {
            "DOI": "10.1/x",
            "indexed": {"date-time": "2026-01-01T00:00:00Z", "date-parts": [[2026, 1, 1]]},
            "deposited": {"date-time": "2025-06-01T00:00:00Z"},
            "created": {"date-time": "2020-01-01T00:00:00Z"},
        }
        result = _normalize_work(item)
        assert result["indexed_date"] == "2026-01-01T00:00:00Z"
        assert result["deposited_date"] == "2025-06-01T00:00:00Z"
        assert result["created_date"] == "2020-01-01T00:00:00Z"
        # Original nested objects are preserved alongside the flattened columns.
        assert result["indexed"]["date-time"] == "2026-01-01T00:00:00Z"

    def test_missing_date_fields_are_skipped(self) -> None:
        item = {"DOI": "10.1/x"}
        result = _normalize_work(item)
        assert "indexed_date" not in result
        assert "deposited_date" not in result
        assert "created_date" not in result


class TestBuildParams:
    def test_works_incremental_without_watermark_still_sorts(self) -> None:
        params = _build_params(
            "Works",
            None,
            "301",
            None,
            None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="indexed_date",
        )
        assert params["sort"] == "indexed"
        assert params["order"] == "asc"
        assert params["filter"] == "member:301"

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

    def test_works_without_scope_has_no_filter(self) -> None:
        params = _build_params(
            "Works",
            None,
            None,
            None,
            None,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert "filter" not in params

    def test_non_works_endpoint_ignores_scope_and_incremental(self) -> None:
        params = _build_params(
            "Members",
            None,
            "301",
            "100000001",
            "1932-6203",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1),
            incremental_field="indexed_date",
        )
        assert "filter" not in params
        assert "sort" not in params

    def test_mailto_is_included_when_set(self) -> None:
        params = _build_params(
            "Members",
            "me@example.com",
            None,
            None,
            None,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["mailto"] == "me@example.com"


class TestGetRowsCursorPagination:
    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_paginates_across_pages_using_next_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.side_effect = [
            _response(200, {"items": [{"DOI": "1"}], "next-cursor": "c2"}),
            _response(200, {"items": [{"DOI": "2"}], "next-cursor": None}),
        ]

        rows = _collect("Works", _make_manager(), mailto=None, member_id="301", funder_id=None, issn=None)

        assert [r["DOI"] for r in rows] == ["1", "2"]
        assert session.get.call_count == 2
        first_url, second_url = (call.args[0] for call in session.get.call_args_list)
        assert _query(first_url)["cursor"] == "*"
        assert _query(second_url)["cursor"] == "c2"

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_stops_on_empty_items_page(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.side_effect = [
            _response(200, {"items": [{"DOI": "1"}], "next-cursor": "c2"}),
            _response(200, {"items": [], "next-cursor": "c3"}),
        ]

        rows = _collect("Works", _make_manager(), mailto=None, member_id="301", funder_id=None, issn=None)

        assert [r["DOI"] for r in rows] == ["1"]
        assert session.get.call_count == 2

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_stops_when_next_cursor_missing(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.side_effect = [_response(200, {"items": [{"DOI": "1"}]})]

        rows = _collect("Works", _make_manager(), mailto=None, member_id="301", funder_id=None, issn=None)

        assert [r["DOI"] for r in rows] == ["1"]
        assert session.get.call_count == 1

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.side_effect = [_response(200, {"items": [{"DOI": "2"}]})]

        rows = _collect(
            "Works",
            _make_manager(CrossrefResumeConfig(cursor="saved123")),
            mailto=None,
            member_id="301",
            funder_id=None,
            issn=None,
        )

        assert [r["DOI"] for r in rows] == ["2"]
        assert _query(session.get.call_args.args[0])["cursor"] == "saved123"

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_saves_state_only_while_next_cursor_present(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(crossref, "Batcher", _FakeBatcher)
        session = MockSession.return_value
        session.get.side_effect = [
            _response(200, {"items": [{"DOI": "1"}], "next-cursor": "c2"}),
            _response(200, {"items": [{"DOI": "2"}]}),
        ]
        manager = _make_manager()

        _collect("Works", manager, mailto=None, member_id="301", funder_id=None, issn=None)

        manager.save_state.assert_called_once_with(CrossrefResumeConfig(cursor="c2"))

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_works_rows_are_normalized(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.side_effect = [
            _response(
                200,
                {"items": [{"DOI": "1", "indexed": {"date-time": "2026-01-01T00:00:00Z"}}]},
            )
        ]

        rows = _collect("Works", _make_manager(), mailto=None, member_id="301", funder_id=None, issn=None)

        assert rows[0]["indexed_date"] == "2026-01-01T00:00:00Z"

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_non_works_rows_are_not_normalized(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.side_effect = [_response(200, {"items": [{"id": "1"}]})]

        rows = _collect("Members", _make_manager(), mailto=None, member_id=None, funder_id=None, issn=None)

        assert "indexed_date" not in rows[0]

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_mailto_passed_as_redact_value(self, MockSession) -> None:
        """mailto is a user-typed contact email, not a secret, but it should still be kept out
        of logged/captured request URLs like other tracked-session redactions."""
        MockSession.return_value.get.side_effect = [_response(200, {"items": [{"DOI": "1"}]})]

        _collect("Works", _make_manager(), mailto="me@example.com", member_id="301", funder_id=None, issn=None)

        assert MockSession.call_args.kwargs["redact_values"] == ("me@example.com",)

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_no_mailto_passes_no_redact_values(self, MockSession) -> None:
        MockSession.return_value.get.side_effect = [_response(200, {"items": [{"DOI": "1"}]})]

        _collect("Works", _make_manager(), mailto=None, member_id="301", funder_id=None, issn=None)

        assert MockSession.call_args.kwargs["redact_values"] == ()


class TestGetRowsTypesEndpoint:
    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_single_request_with_no_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = _response(200, {"items": [{"id": "journal-article", "label": "Journal Article"}]})

        rows = _collect("Types", _make_manager(), mailto=None, member_id=None, funder_id=None, issn=None)

        assert [r["id"] for r in rows] == ["journal-article"]
        assert session.get.call_count == 1
        assert "cursor" not in _query(session.get.call_args.args[0])


class TestCrossrefSourceResponse:
    def test_works_response_shape(self) -> None:
        response = crossref_source(
            endpoint="Works",
            logger=mock.MagicMock(),
            resumable_source_manager=_make_manager(),
            mailto=None,
            member_id="301",
            funder_id=None,
            issn=None,
        )
        assert response.primary_keys == ["DOI"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_date"]

    def test_members_response_has_no_partitioning(self) -> None:
        response = crossref_source(
            endpoint="Members",
            logger=mock.MagicMock(),
            resumable_source_manager=_make_manager(),
            mailto=None,
            member_id=None,
            funder_id=None,
            issn=None,
        )
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("me@example.com") is True

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_non_200_is_invalid(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=503)
        assert validate_credentials(None) is False

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials(None) is False

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_mailto_included_in_request(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("me@example.com")

        url = mock_session.return_value.get.call_args.args[0]
        assert _query(url)["mailto"] == "me@example.com"

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_mailto_passed_as_redact_value(self, mock_session) -> None:
        """mailto is a user-typed contact email, not a secret, but it should still be kept out
        of logged/captured request URLs like other tracked-session redactions."""
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("me@example.com")

        assert mock_session.call_args.kwargs["redact_values"] == ("me@example.com",)

    @mock.patch(CROSSREF_SESSION_PATCH)
    def test_no_mailto_passes_no_redact_values(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials(None)

        assert mock_session.call_args.kwargs["redact_values"] == ()
