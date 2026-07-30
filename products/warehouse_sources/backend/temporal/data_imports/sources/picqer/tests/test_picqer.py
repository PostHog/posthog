import json
from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.picqer import (
    PicqerResumeConfig,
    _base_url,
    _build_params,
    normalize_account,
    picqer_source,
    to_picqer_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import PAGE_SIZE, PICQER_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the picqer module.
PICQER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.picqer.picqer.make_tracked_session"
)


class TestNormalizeAccount:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("acme", "acme"),
            ("acme.picqer.com", "acme"),
            ("https://acme.picqer.com", "acme"),
            ("acme.picqer.com/", "acme"),
            ("acme-corp", "acme-corp"),
            ("  acme  ", "acme"),
        ],
    )
    def test_valid_accounts(self, value: str, expected: str) -> None:
        assert normalize_account(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "acme/../evil",
            "acme.evil.com",
            "acme@evil.com",
            "",
            "ac me",
            "acme-",
        ],
    )
    def test_invalid_accounts_raise(self, value: str) -> None:
        # The account is the host the stored API key is sent to; a loosened regex would let an org
        # member retarget the credential at a server they control.
        with pytest.raises(ValueError):
            normalize_account(value)

    def test_base_url(self) -> None:
        assert _base_url("acme") == "https://acme.picqer.com/api/v1"


class TestToPicqerDatetime:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2020, 1, 2, 3, 4, 5), "2020-01-02 03:04:05"),
            (date(2020, 1, 2), "2020-01-02 00:00:00"),
            ("2020-01-02T03:04:05", "2020-01-02 03:04:05"),
            ("2020-01-02 03:04:05", "2020-01-02 03:04:05"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        # Picqer's `updated_after` filter expects `YYYY-MM-DD HH:MM:SS`; a broken format silently
        # returns wrong/empty incremental pages.
        assert to_picqer_datetime(value) == expected


class TestBuildParams:
    def test_incremental_endpoint_adds_filter(self) -> None:
        params = _build_params(
            PICQER_ENDPOINTS["purchaseorders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )
        assert params == {"updated_after": "2020-01-02 03:04:05"}

    def test_incremental_endpoint_without_cursor_omits_filter(self) -> None:
        params = _build_params(
            PICQER_ENDPOINTS["purchaseorders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params == {}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # orders exposes only a creation-date filter (`sincedate`), so it syncs full refresh; a
        # cursor must never leak into the request and silently drop updated rows.
        params = _build_params(
            PICQER_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )
        assert params == {}


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _page(n: int) -> Response:
    # Picqer list endpoints return a bare JSON array (no envelope).
    return _response([{"idorder": i} for i in range(n)])


def _make_manager(resume_state: PicqerResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead. The
    prepared request's ``url`` is echoed from the Request so the client's allowed-host check
    (pinned to ``<account>.picqer.com``) passes.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock(url=request.url)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Any:
    return picqer_source(
        account="acme",
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_offset_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page(PAGE_SIZE), _page(3)])

        rows = _rows(_source("orders", _make_manager()))

        assert len(rows) == PAGE_SIZE + 3
        assert [p["offset"] for p in params] == [0, PAGE_SIZE]
        # Offset-only advancement: Picqer has no page-size override, so no `limit` is ever sent.
        assert all("limit" not in p for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page(0)])

        manager = _make_manager()
        rows = _rows(_source("orders", manager))

        assert rows == []
        assert [p["offset"] for p in params] == [0]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_offset_only_while_more_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page(PAGE_SIZE), _page(1)])

        manager = _make_manager()
        _rows(_source("orders", manager))

        # State is saved after the full first page (advance to PAGE_SIZE), never after the short
        # last page.
        manager.save_state.assert_called_once_with(PicqerResumeConfig(offset=PAGE_SIZE))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page(2)])

        rows = _rows(_source("orders", _make_manager(PicqerResumeConfig(offset=PAGE_SIZE))))

        assert len(rows) == 2
        assert [p["offset"] for p in params] == [PAGE_SIZE]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_present_on_every_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page(PAGE_SIZE), _page(1)])

        _rows(
            _source(
                "purchaseorders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
            )
        )

        # The filter must stay on every paginated request so pagination walks only the filtered set.
        assert all(p.get("updated_after") == "2020-01-02 03:04:05" for p in params)
        assert [p["offset"] for p in params] == [0, PAGE_SIZE]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_sends_no_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page(1)])

        _rows(
            _source(
                "orders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
            )
        )

        assert "updated_after" not in params[0]

    @pytest.mark.parametrize("status", [429, 503])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_codes_recover(self, MockSession, _mock_sleep, status: int) -> None:
        # A transient 429/5xx then success: the client retry recovers and still yields the data.
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=status), _page(1)])

        rows = _rows(_source("orders", _make_manager()))

        assert len(rows) == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status,expected_ok",
        [
            (200, True),
            # 403 = valid key, insufficient scope — accepted at source-create (per-table scope
            # reported separately).
            (403, True),
            (401, False),
            (500, False),
        ],
    )
    @mock.patch(PICQER_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status: int, expected_ok: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)

        ok, code = validate_credentials("acme", "key")

        assert ok is expected_ok
        assert code == status

    @mock.patch(PICQER_SESSION_PATCH)
    def test_transport_error_maps_to_none_status(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")

        ok, code = validate_credentials("acme", "key")

        assert ok is False
        assert code is None

    def test_bad_account_raises_before_probe(self) -> None:
        # A malformed account must fail loud (so the caller can surface a precise message) rather
        # than being swallowed as an unreachable probe.
        with pytest.raises(ValueError):
            validate_credentials("acme.evil.com", "key")
