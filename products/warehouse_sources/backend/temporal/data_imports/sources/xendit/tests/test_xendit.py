import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.settings import (
    PAGE_SIZE,
    XENDIT_BASE_URL,
    XENDIT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.xendit import (
    XenditResumeConfig,
    _build_params,
    _format_datetime,
    validate_credentials,
    xendit_source,
)

# Both the REST client's session and the credential probe are built by this module's
# make_tracked_session, so one patch target covers the whole transport.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.xendit.xendit.make_tracked_session"


def _response(items: list[dict[str, Any]] | None, has_more: bool, status: int = 200) -> Response:
    body: dict[str, Any] = {"data": items or [], "has_more": has_more, "links": []}
    response = Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    return response


def _make_manager(resume_state: XenditResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params at send time.

    ``request.params`` is one dict mutated in place across pages, so copy it as each request is
    prepared rather than inspecting the shared final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> SourceResponse:
    return xendit_source("xnd_key", endpoint, team_id=1, job_id="job-1", resumable_source_manager=manager, **kwargs)


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("2026-03-04T02:58:14.000Z", "2026-03-04T02:58:14.000Z"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        result = _format_datetime(value)

        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_full_refresh_only_sets_page_size(self) -> None:
        params = _build_params(
            XENDIT_ENDPOINTS["transactions"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated",
        )

        assert params == {"limit": PAGE_SIZE}

    def test_first_incremental_sync_sends_no_filter(self) -> None:
        params = _build_params(
            XENDIT_ENDPOINTS["transactions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated",
        )

        assert params == {"limit": PAGE_SIZE}

    @pytest.mark.parametrize("endpoint", sorted(XENDIT_ENDPOINTS))
    @pytest.mark.parametrize(
        "incremental_field, expected_param", [("updated", "updated[gte]"), ("created", "created[gte]")]
    )
    def test_honors_the_selected_cursor_field(self, endpoint: str, incremental_field: str, expected_param: str) -> None:
        params = _build_params(
            XENDIT_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=incremental_field,
        )

        assert params[expected_param] == "2026-03-04T02:58:14.000Z"
        assert len(params) == 2

    @pytest.mark.parametrize("incremental_field", [None, "estimated_settlement_time"])
    def test_unfilterable_cursor_field_falls_back_to_updated(self, incremental_field: str | None) -> None:
        # A field Xendit does not filter on server-side would be silently ignored, turning the
        # sync into a full refresh that claims to be incremental.
        params = _build_params(
            XENDIT_ENDPOINTS["transactions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=incremental_field,
        )

        assert params["updated[gte]"] == "2026-03-04T02:58:14.000Z"
        assert "estimated_settlement_time[gte]" not in params


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected_valid", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(SESSION_PATCH)
    def test_status_is_reported_back(self, mock_session_factory, status_code: int, expected_valid: bool) -> None:
        mock_session_factory.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        reachable, status = validate_credentials("xnd_key", "/transactions")

        assert (reachable, status) == (expected_valid, status_code)
        call = mock_session_factory.return_value.get.call_args
        assert call.args[0] == f"{XENDIT_BASE_URL}/transactions?limit=1"
        assert call.kwargs["headers"] is None

    @mock.patch(SESSION_PATCH)
    def test_sub_account_header_is_sent(self, mock_session_factory) -> None:
        mock_session_factory.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("xnd_key", "/transactions", for_user_id="sub-1")

        assert mock_session_factory.return_value.get.call_args.kwargs["headers"] == {"for-user-id": "sub-1"}

    @mock.patch(SESSION_PATCH)
    def test_transport_error_is_swallowed(self, mock_session_factory) -> None:
        mock_session_factory.return_value.get.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("xnd_key", "/transactions") == (False, None)


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_follows_after_id_until_has_more_is_false(self, mock_session_factory) -> None:
        params = _wire(
            mock_session_factory.return_value,
            [
                _response([{"id": "txn_1"}, {"id": "txn_2"}], has_more=True),
                _response([{"id": "txn_3"}], has_more=False),
            ],
        )

        rows = _rows(_source("transactions", _make_manager()))

        assert [row["id"] for row in rows] == ["txn_1", "txn_2", "txn_3"]
        assert params[0] == {"limit": PAGE_SIZE}
        # The cursor is the LAST row of the previous page, not the first.
        assert params[1]["after_id"] == "txn_2"

    @mock.patch(SESSION_PATCH)
    def test_stops_when_the_cursor_does_not_advance(self, mock_session_factory) -> None:
        # An API that keeps claiming has_more while returning the same last row would otherwise
        # be refetched until the activity times out.
        mock_session_factory.return_value.headers = {}
        mock_session_factory.return_value.prepare_request.return_value = mock.MagicMock()
        mock_session_factory.return_value.send.side_effect = [
            _response([{"id": "txn_1"}], has_more=True),
            _response([{"id": "txn_1"}], has_more=True),
        ]

        rows = _rows(_source("transactions", _make_manager()))

        assert [row["id"] for row in rows] == ["txn_1", "txn_1"]
        assert mock_session_factory.return_value.send.call_count == 2

    @pytest.mark.parametrize(
        "last_page",
        [
            _response([], has_more=True),
            _response([{"no_id": True}], has_more=True),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_stops_when_no_cursor_can_be_built(self, mock_session_factory, last_page: Response) -> None:
        _wire(mock_session_factory.return_value, [last_page])

        _rows(_source("transactions", _make_manager()))

        assert mock_session_factory.return_value.send.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_saves_resume_state_after_each_page_but_not_the_last(self, mock_session_factory) -> None:
        _wire(
            mock_session_factory.return_value,
            [_response([{"id": "txn_1"}], has_more=True), _response([{"id": "txn_2"}], has_more=False)],
        )
        manager = _make_manager()

        _rows(_source("transactions", manager))

        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == XenditResumeConfig(after_id="txn_1")

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, mock_session_factory) -> None:
        params = _wire(mock_session_factory.return_value, [_response([{"id": "txn_9"}], has_more=False)])

        rows = _rows(_source("transactions", _make_manager(XenditResumeConfig(after_id="txn_8"))))

        assert [row["id"] for row in rows] == ["txn_9"]
        assert params[0]["after_id"] == "txn_8"

    @mock.patch(SESSION_PATCH)
    def test_incremental_filter_rides_the_first_request(self, mock_session_factory) -> None:
        params = _wire(mock_session_factory.return_value, [_response([{"id": "txn_1"}], has_more=False)])

        _rows(
            _source(
                "transactions",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="updated",
            )
        )

        assert params[0]["updated[gte]"] == "2026-03-04T02:58:14.000Z"

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(SESSION_PATCH)
    def test_retries_transient_statuses(self, mock_session_factory, _mock_sleep) -> None:
        _wire(
            mock_session_factory.return_value,
            [
                _response(None, has_more=False, status=429),
                _response(None, has_more=False, status=503),
                _response([{"id": "txn_1"}], has_more=False),
            ],
        )

        rows = _rows(_source("transactions", _make_manager()))

        assert [row["id"] for row in rows] == ["txn_1"]
        assert mock_session_factory.return_value.send.call_count == 3

    @mock.patch(SESSION_PATCH)
    def test_forbidden_response_raises(self, mock_session_factory) -> None:
        _wire(mock_session_factory.return_value, [_response(None, has_more=False, status=403)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("transactions", _make_manager()))


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", sorted(XENDIT_ENDPOINTS))
    @mock.patch(SESSION_PATCH)
    def test_response_shape(self, mock_session_factory, endpoint: str) -> None:
        mock_session_factory.return_value.headers = {}

        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Xendit documents no ordering direction on these endpoints, so the watermark must only be
        # committed once a run completes.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        # The partition key must be a field that never changes after a row is written.
        assert response.partition_keys == ["created"]
