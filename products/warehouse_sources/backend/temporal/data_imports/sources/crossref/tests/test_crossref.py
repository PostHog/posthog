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
