import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.reverb import (
    ReverbResumeConfig,
    _format_datetime,
    _inject_payout_id,
    reverb_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.settings import PER_PAGE

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
REVERB_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.reverb.reverb.make_tracked_session"
)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("string_passthrough", "not-a-date", "not-a-date"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_future_datetime_is_capped_at_now(self) -> None:
        far_future = datetime(2999, 1, 1, tzinfo=UTC)
        result = _format_datetime(far_future)
        assert result != "2999-01-01T00:00:00Z"
        assert result < "2999-01-01T00:00:00Z"


class TestInjectPayoutId:
    @parameterized.expand(
        [
            (
                "well_formed_href",
                {"_links": {"line_items": {"href": "https://api.reverb.com/api/my/payouts/54/line_items"}}},
                54,
            ),
            ("missing_links", {}, None),
            ("missing_line_items", {"_links": {}}, None),
            ("malformed_href", {"_links": {"line_items": {"href": "not-a-url"}}}, None),
        ]
    )
    def test_id_extraction(self, _name: str, row: dict[str, Any], expected_id: int | None) -> None:
        result = _inject_payout_id(dict(row))
        assert result.get("id") == expected_id


def _response(
    response_key: str,
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    drop_key: bool = False,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_key:
        body[response_key] = items or []
    if current_page is not None:
        body["current_page"] = current_page
    if total_pages is not None:
        body["total_pages"] = total_pages
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ReverbResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    kwargs.setdefault("should_use_incremental_field", False)
    kwargs.setdefault("db_incremental_field_last_value", None)
    kwargs.setdefault("api_version", "3.0")
    return reverb_source(
        api_token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestReverbSourceOrders:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_pages(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response("orders", [{"order_number": "1"}, {"order_number": "2"}], current_page=1, total_pages=2),
                _response("orders", [{"order_number": "3"}], current_page=2, total_pages=2),
            ],
        )

        rows = _rows(_source("Orders", _make_manager()))

        assert [r["order_number"] for r in rows] == ["1", "2", "3"]
        # total_pages=2 terminates after the last page — no extra empty-page request.
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == "https://api.reverb.com/api/my/orders/selling/all"
        assert snapshots[0]["params"] == {"per_page": PER_PAGE, "page": 1}
        assert snapshots[1]["params"] == {"per_page": PER_PAGE, "page": 2}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_is_framework_bearer(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("orders", [{"order_number": "1"}], total_pages=1)])

        _rows(_source("Orders", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "token"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response("orders", [{"order_number": "1"}], current_page=1, total_pages=2),
                _response("orders", [{"order_number": "2"}], current_page=2, total_pages=2),
            ],
        )

        manager = _make_manager()
        _rows(_source("Orders", manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ReverbResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("orders", [{"order_number": "2"}], current_page=2, total_pages=2)])

        rows = _rows(_source("Orders", _make_manager(ReverbResumeConfig(next_page=2))))

        assert [r["order_number"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_window_added_to_request(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("orders", [{"order_number": "1"}], total_pages=1)])

        _rows(
            _source(
                "Orders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["updated_start_date"] == "2026-03-04T02:58:14Z"
        assert "updated_end_date" in snapshots[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_window_when_not_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("orders", [{"order_number": "1"}], total_pages=1)])

        _rows(_source("Orders", _make_manager(), should_use_incremental_field=False))

        assert "updated_start_date" not in snapshots[0]["params"]
        assert "updated_end_date" not in snapshots[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_write_disposition_is_merge_when_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("orders", [{"order_number": "1"}], total_pages=1)])

        response = _source(
            "Orders",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert response.primary_keys == ["order_number"]
        assert response.sort_mode == "desc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("orders", [], total_pages=1)])

        manager = _make_manager()
        rows = _rows(_source("Orders", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_metadata_partial_page_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("orders", [{"order_number": "1"}, {"order_number": "2"}])])

        rows = _rows(_source("Orders", _make_manager()))

        assert [r["order_number"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_metadata_full_page_continues(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"order_number": str(i)} for i in range(PER_PAGE)]
        _wire(session, [_response("orders", full_page), _response("orders", [{"order_number": "last"}])])

        rows = _rows(_source("Orders", _make_manager()))

        assert len(rows) == PER_PAGE + 1
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_required_headers_are_sent(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("orders", [{"order_number": "1"}], total_pages=1)])

        _rows(_source("Orders", _make_manager(), api_version="3.0"))

        assert session.headers["Accept"] == "application/hal+json"
        assert session.headers["Content-Type"] == "application/hal+json"
        assert session.headers["Accept-Version"] == "3.0"


class TestReverbSourceListings:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_ignores_incremental_flag(self, MockSession) -> None:
        # Listings has no documented date-window filter, so it must stay full refresh even
        # when the caller asks for incremental sync.
        session = MockSession.return_value
        snapshots = _wire(session, [_response("listings", [{"id": 1}], total_pages=1)])

        response = _source(
            "Listings",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        _rows(response)

        assert "updated_start_date" not in snapshots[0]["params"]
        assert response.primary_keys == ["id"]


class TestReverbSourcePayouts:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_derives_id_from_line_items_href(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    "payouts",
                    [
                        {
                            "total": {"amount": "11.88"},
                            "_links": {"line_items": {"href": "https://api.reverb.com/api/my/payouts/54/line_items"}},
                        }
                    ],
                    total_pages=1,
                )
            ],
        )

        rows = _rows(_source("Payouts", _make_manager()))

        assert rows[0]["id"] == 54

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_window_uses_created_date_params(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("payouts", [], total_pages=1)])

        _rows(
            _source(
                "Payouts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["created_start_date"] == "2026-03-04T00:00:00Z"
        assert "created_end_date" in snapshots[0]["params"]


class TestValidateCredentials:
    @mock.patch(REVERB_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("token", "3.0") == (True, 200)

    @mock.patch(REVERB_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("token", "3.0") == (False, 401)

    @mock.patch(REVERB_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token", "3.0") == (False, None)

    @mock.patch(REVERB_SESSION_PATCH)
    def test_probes_my_account_with_required_headers(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("token", "3.0")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.reverb.com/api/my/account"
        headers = call.kwargs["headers"]
        assert headers["Authorization"] == "Bearer token"
        assert headers["Accept-Version"] == "3.0"


@pytest.mark.parametrize("status_code", [200, 401, 403, 500])
def test_validate_credentials_maps_status_codes(status_code) -> None:
    with mock.patch(REVERB_SESSION_PATCH) as mock_session:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        ok, code = validate_credentials("token", "3.0")
        assert ok is (status_code == 200)
        assert code == status_code
