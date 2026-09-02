import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.flutterwave import (
    EARLIEST_WINDOW_START,
    FlutterwaveResumeConfig,
    base_url,
    flutterwave_source,
    validate_credentials,
)

# get_rows builds the tracked session (capture=False) and hands it to the REST client, and
# validate_credentials builds its probe session, both via this import — so one patch covers both.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.flutterwave.make_tracked_session"
)
SLEEP_PATCH = "tenacity.nap.time.sleep"

BASE_URL = base_url("v3")


def _response(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = f"{BASE_URL}/transactions"
    resp.headers["Content-Type"] = "application/json"
    resp._content = b"" if body is None else json.dumps(body).encode()
    return resp


def _page(rows: list[dict[str, Any]], total_pages: int = 1) -> dict[str, Any]:
    return {
        "status": "success",
        "message": "fetched",
        "meta": {"page_info": {"total": len(rows), "current_page": 1, "total_pages": total_pages}},
        "data": rows,
    }


def _make_manager(resume_state: FlutterwaveResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    auth_snapshots: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        auth_snapshots.append(request.auth)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, auth_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any) -> Any:
    return flutterwave_source(
        secret_key="FLWSECK-test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        api_version="v3",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_walks_pages_until_total_pages(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, auths = _wire(
            session,
            [_response(_page([{"id": 1}], total_pages=2)), _response(_page([{"id": 2}], total_pages=2))],
        )

        rows = _rows(_source("subaccounts"))

        assert [r["id"] for r in rows] == [1, 2]
        # Stops on meta.page_info.total_pages instead of paying for an extra empty page.
        assert session.send.call_count == 2
        assert [p["page"] for p in params] == [1, 2]
        # The secret rides on framework bearer auth, never a query param.
        assert auths[0].token == "FLWSECK-test"
        assert "seckey" not in params[0]

    @mock.patch(SESSION_PATCH)
    def test_empty_page_stops_pagination(self, MockSession: mock.MagicMock) -> None:
        # A body that claims more pages than it has must not loop forever on empty responses.
        session = MockSession.return_value
        _wire(session, [_response(_page([], total_pages=9))])

        assert _rows(_source("subaccounts")) == []
        assert session.send.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _auths = _wire(session, [_response(_page([{"id": 7}], total_pages=4))])

        rows = _rows(_source("subaccounts", _make_manager(FlutterwaveResumeConfig(next_page=4))))

        assert [r["id"] for r in rows] == [7]
        assert params[0]["page"] == 4

    @mock.patch(SESSION_PATCH)
    def test_saves_page_after_yielding_and_only_while_pages_remain(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [_response(_page([{"id": 1}], total_pages=2)), _response(_page([{"id": 2}], total_pages=2))],
        )

        manager = _make_manager()
        _rows(_source("subaccounts", manager))

        # Only page 1 has a page after it, so exactly one checkpoint is written and it points at 2.
        assert [c.args[0] for c in manager.save_state.call_args_list] == [FlutterwaveResumeConfig(next_page=2)]


class TestDateWindow:
    @parameterized.expand(
        [
            ("settlements",),
            ("refunds",),
            ("transfers",),
            ("chargebacks",),
            ("payment_plans",),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_optional_window_endpoints_send_no_window_on_full_refresh(
        self, endpoint: str, MockSession: mock.MagicMock
    ) -> None:
        # A full refresh must pull the whole history; a stray `from` would silently truncate it.
        session = MockSession.return_value
        params, _auths = _wire(session, [_response(_page([{"id": 1}]))])

        _rows(
            _source(
                endpoint,
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2024, 1, 15, tzinfo=UTC),
            )
        )

        assert "from" not in params[0]
        assert "to" not in params[0]

    @parameterized.expand(
        [
            ("subscriptions",),
            ("subaccounts",),
            ("beneficiaries",),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_endpoints_without_a_window_never_send_one(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        # These endpoints do not accept `from`/`to`; sending them risks 4xxing the whole run.
        session = MockSession.return_value
        params, _auths = _wire(session, [_response(_page([{"id": 1}]))])

        _rows(_source(endpoint, should_use_incremental_field=False, db_incremental_field_last_value=None))

        assert "from" not in params[0]
        assert "to" not in params[0]

    @freeze_time("2026-06-15T23:30:00Z")
    @mock.patch(SESSION_PATCH)
    def test_transactions_always_sends_the_required_window(self, MockSession: mock.MagicMock) -> None:
        # /transactions documents `from`/`to` as required, so every full refresh sends the whole
        # history window. `to` is padded a day past UTC today so records booked "today" in a timezone
        # ahead of UTC are not clipped.
        session = MockSession.return_value
        params, _auths = _wire(session, [_response(_page([{"id": 1}]))])

        _rows(_source("transactions", should_use_incremental_field=False, db_incremental_field_last_value=None))

        assert params[0]["from"] == EARLIEST_WINDOW_START
        assert params[0]["to"] == "2026-06-16"


class TestNoRecordsResponses:
    @parameterized.expand(
        [
            ("lowercase", {"status": "error", "message": "No settlements found", "data": None}),
            ("capitalized", {"status": "error", "message": "Transaction Not Found", "data": None}),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_empty_range_400_reads_as_an_empty_table(
        self, _name: str, body: dict[str, Any], MockSession: mock.MagicMock
    ) -> None:
        # v3 answers "no records in this range" with a 400 on some list endpoints; a merchant with an
        # empty table must sync zero rows rather than fail the job.
        session = MockSession.return_value
        _wire(session, [_response(body, status=400, reason="Bad Request")])

        assert _rows(_source("settlements")) == []
        assert session.send.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_genuine_parameter_error_still_raises(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    {"status": "error", "message": "page parameter must be a positive integer", "data": None},
                    status=400,
                    reason="Bad Request",
                )
            ],
        )

        with pytest.raises(requests.HTTPError):
            _rows(_source("settlements"))


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @mock.patch(SESSION_PATCH)
    def test_credential_errors_surface_the_matchable_message(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock
    ) -> None:
        # get_non_retryable_errors matches on this exact status text plus host, so it must not be
        # swallowed or retried.
        session = MockSession.return_value
        _wire(session, [_response({"status": "error"}, status=status, reason=reason)])

        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(_source("transactions"))
        assert f"{status} Client Error" in str(exc_info.value)
        assert "https://api.flutterwave.com" in str(exc_info.value)
        assert session.send.call_count == 1

    @parameterized.expand([("rate_limited", 429, "Too Many Requests"), ("server_error", 503, "Service Unavailable")])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_transient_statuses_are_retried_by_the_transport(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status, reason=reason), _response(_page([{"id": 1}]))])

        assert [r["id"] for r in _rows(_source("transactions"))] == [1]
        assert session.send.call_count == 2

    @mock.patch(SLEEP_PATCH)
    @mock.patch(SESSION_PATCH)
    def test_persistent_rate_limit_raises_retryable(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=429, reason="Too Many Requests")] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("transactions"))


class TestSourceResponseMetadata:
    @parameterized.expand(
        [
            ("transactions",),
            ("settlements",),
            ("refunds",),
            ("transfers",),
            ("chargebacks",),
            ("payment_plans",),
            ("subscriptions",),
            ("subaccounts",),
            ("beneficiaries",),
        ]
    )
    def test_every_endpoint_partitions_on_created_at(self, endpoint: str) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Every endpoint is full-refresh, so the pipeline never consults sort_mode; it stays the
        # framework default.
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            # v3 answers "no subaccounts on this account" with a 400; the key was still accepted.
            ("no_records", 400, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_maps_to_validity(self, _name: str, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(SESSION_PATCH, return_value=session):
            valid, message = validate_credentials("FLWSECK-test", "v3")
        assert valid is expected
        assert (message is None) is expected

    def test_network_failure_is_not_valid(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(SESSION_PATCH, return_value=session):
            valid, message = validate_credentials("FLWSECK-test", "v3")
        assert valid is False
        assert message is not None

    def test_probe_targets_the_pinned_api_version(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(SESSION_PATCH, return_value=session):
            validate_credentials("FLWSECK-test", "v3")
        assert session.get.call_args.args[0] == "https://api.flutterwave.com/v3/subaccounts"
