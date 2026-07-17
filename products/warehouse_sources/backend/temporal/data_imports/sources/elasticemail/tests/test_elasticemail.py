import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail import elasticemail
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.elasticemail import (
    AUTH_ERROR_MARKER,
    ElasticEmailResumeConfig,
    _build_url,
    _clamp_future_value_to_now,
    _format_datetime,
    _is_auth_error_body,
    _static_params,
    elasticemail_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.settings import (
    ELASTICEMAIL_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the elasticemail module.
ELASTICEMAIL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.elasticemail.make_tracked_session"
)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_offset_suffix(self) -> None:
        # Elastic Email expects YYYY-MM-DDThh:mm:ss with no timezone offset.
        result = _format_datetime(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+" not in result and "Z" not in result


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, tzinfo=UTC)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor") == "cursor"


class TestStaticParams:
    def test_events_incremental_adds_from_filter(self) -> None:
        params = _static_params(
            ELASTICEMAIL_ENDPOINTS["events"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params["from"] == "2026-03-04T02:58:14"
        assert params["orderBy"] == "DateAscending"

    def test_events_without_cursor_has_no_from(self) -> None:
        params = _static_params(
            ELASTICEMAIL_ENDPOINTS["events"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert "from" not in params

    def test_full_refresh_endpoint_never_adds_from(self) -> None:
        # Contacts has no server-side time filter, so a cursor value must not leak into the request.
        params = _static_params(
            ELASTICEMAIL_ENDPOINTS["contacts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "from" not in params

    def test_templates_carries_required_scope_type(self) -> None:
        params = _static_params(
            ELASTICEMAIL_ENDPOINTS["templates"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params["scopeType"] == ["Personal", "Global"]


class TestBuildUrl:
    def test_expands_list_params_into_repeated_query(self) -> None:
        url = _build_url("/templates", {"limit": 1, "scopeType": ["Personal", "Global"]})
        assert url == "https://api.elasticemail.com/v4/templates?limit=1&scopeType=Personal&scopeType=Global"


class TestIsAuthErrorBody:
    @parameterized.expand(
        [
            ("401", 401, "", True),
            ("403", 403, "", True),
            ("400_apikey_expired", 400, '{"Error":"APIKey Expired"}', True),
            ("400_incorrect_key", 400, '{"Error":"Incorrect API key."}', True),
            ("400_generic_bad_request", 400, '{"Error":"Invalid date range"}', False),
            ("404", 404, '{"Error":"Not found"}', False),
            ("200", 200, "[]", False),
        ]
    )
    def test_is_auth_error_body(self, _name: str, status: int, body: str, expected: bool) -> None:
        assert _is_auth_error_body(status, body) is expected


def _make_response(status_code: int, *, json_body: Any = None, text: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    if json_body is not None:
        response._content = json.dumps(json_body).encode()
    elif text is not None:
        response._content = text.encode()
    return response


def _make_manager(resume_state: ElasticEmailResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than reading the shared dict after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return elasticemail_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession: Any) -> None:
        session = MockSession.return_value
        full_page = [{"Email": f"c{i}@x.com"} for i in range(elasticemail.PAGE_SIZE)]
        params = _wire(
            session,
            [_make_response(200, json_body=full_page), _make_response(200, json_body=[{"Email": "last@x.com"}])],
        )

        rows = _rows(_source("contacts", _make_manager()))

        assert [r["Email"] for r in rows] == [*(f"c{i}@x.com" for i in range(elasticemail.PAGE_SIZE)), "last@x.com"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == elasticemail.PAGE_SIZE
        assert params[1]["offset"] == elasticemail.PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_make_response(200, json_body=[{"Email": "a@x.com"}, {"Email": "b@x.com"}])])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert [r["Email"] for r in rows] == ["a@x.com", "b@x.com"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_offset_after_each_non_final_page(self, MockSession: Any) -> None:
        session = MockSession.return_value
        full_page = [{"Email": f"c{i}@x.com"} for i in range(elasticemail.PAGE_SIZE)]
        _wire(
            session,
            [_make_response(200, json_body=full_page), _make_response(200, json_body=[{"Email": "last@x.com"}])],
        )

        manager = _make_manager()
        _rows(_source("contacts", manager))

        # State is saved after the full page (points at the next page); the short final page saves nothing.
        assert [c.args[0] for c in manager.save_state.call_args_list] == [
            ElasticEmailResumeConfig(offset=elasticemail.PAGE_SIZE)
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_make_response(200, json_body=[{"Email": "resumed@x.com"}])])

        manager = _make_manager(ElasticEmailResumeConfig(offset=2000))
        rows = _rows(_source("contacts", manager))

        assert params[0]["offset"] == 2000
        assert [r["Email"] for r in rows] == ["resumed@x.com"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_terminates(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_make_response(200, json_body=[])])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_incremental_from_filter_reaches_request(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_make_response(200, json_body=[{"MsgID": "m1"}])])

        _rows(
            _source(
                "events",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert params[0]["from"] == "2026-03-04T02:58:14"
        assert params[0]["orderBy"] == "DateAscending"


def _wire_repeating(session: mock.MagicMock, response: requests.Response) -> None:
    """Return the same response for every send — a retryable status is re-issued until attempts run out."""
    session.headers = {}
    session.prepare_request.side_effect = lambda request: mock.MagicMock()
    session.send.return_value = response


class TestErrorClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_raise_retryable(self, _name: str, status: int, MockSession: Any, _sleep: Any) -> None:
        session = MockSession.return_value
        _wire_repeating(session, _make_response(status, text="boom"))
        with pytest.raises(RESTClientRetryableError):
            _rows(_source("contacts", _make_manager()))

    @parameterized.expand(
        [
            ("expired_key_400", 400, '{"Error":"APIKey Expired"}'),
            ("incorrect_key_400", 400, '{"Error":"Incorrect API key."}'),
            ("unauthorized_401", 401, ""),
            ("forbidden_403", 403, ""),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_failures_raise_marked_error(self, _name: str, status: int, body: str, MockSession: Any) -> None:
        # A bad/expired/under-scoped key surfaces a permanent, marker-carrying error so the pipeline's
        # non-retryable classifier stops the sync instead of hammering the dead key.
        session = MockSession.return_value
        _wire(session, [_make_response(status, text=body)])
        with pytest.raises(ValueError) as exc:
            _rows(_source("contacts", _make_manager()))
        assert AUTH_ERROR_MARKER in str(exc.value)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_generic_400_is_not_marked_as_auth(self, MockSession: Any) -> None:
        # A non-credential 400 raises an HTTPError with no auth marker, so the pipeline retries it as usual.
        session = MockSession.return_value
        _wire(session, [_make_response(400, text='{"Error":"Invalid date range"}')])
        with pytest.raises(requests.HTTPError) as exc:
            _rows(_source("contacts", _make_manager()))
        assert AUTH_ERROR_MARKER not in str(exc.value)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_payload_raises_shape_error(self, MockSession: Any) -> None:
        # A 200 object payload is an unexpected shape; fail loud rather than sync the object as a row.
        # The error carries no auth marker, so the pipeline retries it as a transient shape change.
        session = MockSession.return_value
        _wire(session, [_make_response(200, json_body={"Error": "unexpected"})])
        with pytest.raises(ValueError) as exc:
            _rows(_source("contacts", _make_manager()))
        assert AUTH_ERROR_MARKER not in str(exc.value)

    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_json_body_raises_retryable(self, MockSession: Any, _sleep: Any) -> None:
        # A 200 with an HTML/proxy body must not propagate a raw JSONDecodeError; it is retried.
        session = MockSession.return_value
        _wire_repeating(session, _make_response(200, text="<html>gateway timeout</html>"))
        with pytest.raises(RESTClientRetryableError):
            _rows(_source("contacts", _make_manager()))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, "[]", True),
            ("expired_key", 400, '{"Error":"APIKey Expired"}', False),
            ("unauthorized", 401, "", False),
            ("forbidden", 403, "", False),
            # A non-auth error (e.g. a transient 500) should not be reported as an invalid key.
            ("server_error", 500, "boom", True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, body: str, expected: bool) -> None:
        with mock.patch.object(
            elasticemail,
            "make_tracked_session",
            lambda **_: _FakeSession(_make_response(status, text=body)),
        ):
            assert validate_credentials("key") is expected

    def test_transport_exception_is_invalid(self) -> None:
        class _Boom:
            def get(self, *a: Any, **k: Any) -> Any:
                raise requests.ConnectionError("down")

        with mock.patch.object(elasticemail, "make_tracked_session", lambda **_: _Boom()):
            assert validate_credentials("key") is False


class _FakeSession:
    def __init__(self, response: requests.Response) -> None:
        self._response = response

    def get(self, url: str, headers: dict[str, str], timeout: int) -> requests.Response:
        return self._response


class TestElasticemailSource:
    @parameterized.expand(
        [
            ("contacts", ["Email"], "DateAdded"),
            ("lists", ["ListName"], "DateAdded"),
            ("segments", ["Name"], None),
            ("campaigns", ["Name"], None),
            ("templates", ["Name"], "DateAdded"),
            ("events", ["TransactionID", "MsgID", "EventType", "EventDate"], "EventDate"),
            ("suppressions", ["Email"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "week"
