import json
import base64
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.mailjet import (
    MAILJET_BASE_URL,
    WEBHOOK_PATH,
    MailjetResumeConfig,
    _authenticated_callback_url,
    _to_unix_ts,
    _webhook_table_transformer,
    _without_credentials,
    create_webhook,
    delete_webhook,
    expected_authorization_header,
    get_external_webhook_info,
    mailjet_source,
    sync_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import (
    MAILJET_ENDPOINTS,
    MAILJET_WEBHOOK_EVENTS,
    WEBHOOK_TABLE_NAME,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the mailjet module.
MAILJET_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session"
)


def _response(rows: list[dict[str, Any]] | None, total: int | None = None, *, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {}
    if not drop_data:
        body["Data"] = rows or []
    if total is not None:
        body["Total"] = total
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b'{"ErrorMessage": "boom"}'
    return resp


def _make_manager(resume_state: MailjetResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session; capture each request's params and the request object AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy per page.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    requests_seen: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        requests_seen.append(request)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, requests_seen


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    kwargs.setdefault("webhook_source_manager", mock.MagicMock())
    return mailjet_source("key", "secret", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


LIMIT = MAILJET_ENDPOINTS["contact"].page_size


class TestToUnixTs:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 1, tzinfo=UTC), 1767225600),
            ("naive_datetime", datetime(2026, 1, 1), 1767225600),
            ("int_passthrough", 1767225600, 1767225600),
            ("none", None, None),
            ("string", "not-a-ts", None),
        ]
    )
    def test_to_unix_ts(self, _name: str, value: object, expected: int | None) -> None:
        assert _to_unix_ts(value) == expected


class TestAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_basic_auth_wired_from_credentials(self, MockSession) -> None:
        session = MockSession.return_value
        _params, requests_seen = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(_source("contact", _make_manager()))

        auth = requests_seen[0].auth
        encoded = base64.b64encode(b"key:secret").decode()
        # HttpBasicAuth emits exactly `Basic base64(key:secret)`.
        assert auth.username == "key"
        assert auth.password == "secret"
        assert base64.b64encode(f"{auth.username}:{auth.password}".encode()).decode() == encoded


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"ID": i} for i in range(3)], total=3)])

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == 3
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_multi_page_advances_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(
            session,
            [
                _response([{"ID": i} for i in range(LIMIT)], total=LIMIT + 2),
                _response([{"ID": i} for i in range(2)], total=LIMIT + 2),
            ],
        )

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == LIMIT + 2
        assert session.send.call_count == 2
        assert params[0]["Offset"] == 0
        assert params[0]["Limit"] == LIMIT
        assert params[1]["Offset"] == LIMIT

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_exact_multiple_terminates_via_total(self, MockSession) -> None:
        session = MockSession.return_value
        # A full page whose length == limit but Total is reached must stop without a second request.
        _wire(session, [_response([{"ID": i} for i in range(LIMIT)], total=LIMIT)])

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == LIMIT
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], total=0)])

        source = _source("contact", _make_manager())
        assert _rows(source) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_treated_as_empty(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, total=0, drop_data=True)])

        # A 200 body without "Data" is lenient — no rows, no raise (matches the prior implementation).
        source = _source("contact", _make_manager())
        assert _rows(source) == []
        assert session.send.call_count == 1

    @parameterized.expand([(name,) for name in MAILJET_ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sort_param_sent(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(_source(endpoint, _make_manager()))

        assert params[0]["Sort"] == MAILJET_ENDPOINTS[endpoint].sort

    def test_campaigndraft_does_not_sort_on_created_at(self) -> None:
        # Regression guard for the Sort fallback documented in settings.py.
        assert MAILJET_ENDPOINTS["campaigndraft"].sort == "ID"


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=2000)])

        manager = _make_manager(MailjetResumeConfig(offset=1000, endpoint="contact"))
        _rows(_source("contact", manager))

        assert params[0]["Offset"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_ignored_for_other_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        manager = _make_manager(MailjetResumeConfig(offset=1000, endpoint="campaign"))
        _rows(_source("contact", manager))

        assert params[0]["Offset"] == 0

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_saves_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"ID": i} for i in range(3)], total=3)])

        manager = _make_manager()
        _rows(_source("contact", manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_saved_after_each_page_with_successor(self, MockSession) -> None:
        # State is persisted after every page that has a successor, carrying the next offset and the
        # endpoint. The final page saves nothing (sync is complete). A crash re-yields the last page,
        # which merge dedupes on the primary key.
        session = MockSession.return_value
        _wire(
            session,
            [_response([{"ID": i} for i in range(p * LIMIT, (p + 1) * LIMIT)], total=3 * LIMIT) for p in range(3)],
        )

        manager = _make_manager()
        rows = _rows(_source("contact", manager))

        assert len(rows) == 3 * LIMIT
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert [s.offset for s in saved] == [LIMIT, 2 * LIMIT]
        assert all(s.endpoint == "contact" for s in saved)


class TestIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_from_ts_applied_for_statistics_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(
            _source(
                "openinformation",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0]["FromTS"] == 1767225600

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_from_ts_not_applied_for_full_refresh_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(
            _source(
                "contact",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "FromTS" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_from_ts_not_applied_without_incremental_flag(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(
            _source(
                "openinformation",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "FromTS" not in params[0]


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name in MAILJET_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        config = MAILJET_ENDPOINTS[endpoint]

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestRetryable:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_429_retries_until_success(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(429), _response([{"ID": 1}], total=1)])

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == 1
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_500_retries_until_success(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(500), _response([{"ID": 1}], total=1)])

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == 1
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_401_does_not_retry_and_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(401)])

        with pytest.raises(Exception):
            _rows(_source("contact", _make_manager()))

        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok_200", 200, True), ("unauthorized_401", 401, False), ("server_500", 500, False)])
    @mock.patch(MAILJET_SESSION_PATCH)
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("key", "secret") is expected

        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{MAILJET_BASE_URL}/contactmetadata?Limit=1"
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        token = headers["Authorization"].removeprefix("Basic ")
        assert base64.b64decode(token).decode() == "key:secret"

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_validate_credentials_network_error_returns_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "secret") is False


WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hog-fn-1"


def _callback_row(event: str, url: str, row_id: int = 1, status: str = "alive") -> dict[str, Any]:
    return {"ID": row_id, "EventType": event, "Url": url, "Status": status, "Version": 1, "IsBackup": False}


def _json_response(body: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    return response


class TestWebhookCallbackUrl:
    def test_credentials_round_trip(self) -> None:
        authed = _authenticated_callback_url(WEBHOOK_URL, "p@ss")
        # The password rides in the URL's userinfo, which is what Mailjet replays as basic auth.
        assert authed.startswith("https://posthog:p@ss@webhooks.us.posthog.com/")
        assert _without_credentials(authed) == WEBHOOK_URL

    def test_url_without_credentials_is_unchanged(self) -> None:
        assert _without_credentials(WEBHOOK_URL) == WEBHOOK_URL

    def test_expected_header_matches_the_registered_credentials(self) -> None:
        header = expected_authorization_header("p@ss")
        assert base64.b64decode(header.removeprefix("Basic ")).decode() == "posthog:p@ss"


class TestCreateWebhook:
    @mock.patch(MAILJET_SESSION_PATCH)
    def test_registers_every_event_type_with_authenticated_url(self, mock_session) -> None:
        session = mock_session.return_value
        session.post.return_value = _json_response({"Data": []}, 201)

        result = create_webhook("key", "secret", WEBHOOK_URL)

        assert result.success is True
        posted = [call.kwargs["json"] for call in session.post.call_args_list]
        assert [body["EventType"] for body in posted] == list(MAILJET_WEBHOOK_EVENTS)
        # Version 1 delivers one event per request; Version 2 would batch them into an array the
        # warehouse webhook pipeline cannot unpack.
        assert {body["Version"] for body in posted} == {1}

        registered_url = posted[0]["Url"]
        assert _without_credentials(registered_url) == WEBHOOK_URL
        password = registered_url.split("posthog:", 1)[1].rsplit("@", 1)[0]
        assert result.extra_inputs == {"authorization_header": expected_authorization_header(password)}

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_partial_failure_still_persists_the_credentials(self, mock_session) -> None:
        # Losing the password would leave the registrations that did land unverifiable forever.
        session = mock_session.return_value
        ok = _json_response({"Data": []}, 201)
        bad = _json_response({}, 400)
        bad.raise_for_status.side_effect = Exception("bad request")
        session.post.side_effect = [ok, bad, ok, ok, ok, ok, ok]

        result = create_webhook("key", "secret", WEBHOOK_URL)

        assert result.success is True
        assert "authorization_header" in result.extra_inputs

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_total_failure_reports_an_error(self, mock_session) -> None:
        session = mock_session.return_value
        response = _json_response({}, 403)
        response.raise_for_status.side_effect = Exception("forbidden")
        session.post.return_value = response

        result = create_webhook("key", "secret", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None
        assert result.extra_inputs == {}


class TestSyncWebhookEvents:
    @mock.patch(MAILJET_SESSION_PATCH)
    def test_registers_only_the_missing_events_reusing_stored_credentials(self, mock_session) -> None:
        session = mock_session.return_value
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        session.get.return_value = _json_response({"Data": [_callback_row("open", authed)]})
        session.post.return_value = _json_response({"Data": []}, 201)

        result = sync_webhook_events("key", "secret", WEBHOOK_URL, ["open", "click"])

        assert result.success is True
        posted = [call.kwargs["json"] for call in session.post.call_args_list]
        assert [body["EventType"] for body in posted] == ["click"]
        # The password only exists on the stored registration, so it has to be carried over.
        assert posted[0]["Url"] == authed

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_no_op_when_every_event_is_registered(self, mock_session) -> None:
        session = mock_session.return_value
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        session.get.return_value = _json_response(
            {"Data": [_callback_row(event, authed, row_id=i) for i, event in enumerate(MAILJET_WEBHOOK_EVENTS)]}
        )

        assert sync_webhook_events("key", "secret", WEBHOOK_URL, list(MAILJET_WEBHOOK_EVENTS)).success is True
        session.post.assert_not_called()

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_ignores_callback_urls_belonging_to_other_destinations(self, mock_session) -> None:
        session = mock_session.return_value
        session.get.return_value = _json_response({"Data": [_callback_row("open", "https://example.com/hook")]})

        assert sync_webhook_events("key", "secret", WEBHOOK_URL, ["open"]).success is True
        session.post.assert_not_called()

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_api_failure_is_reported_not_raised(self, mock_session) -> None:
        session = mock_session.return_value
        session.get.side_effect = Exception("boom")

        result = sync_webhook_events("key", "secret", WEBHOOK_URL, ["open"])

        assert result.success is False
        assert result.error is not None


class TestExternalWebhookInfo:
    @mock.patch(MAILJET_SESSION_PATCH)
    def test_reports_registered_events_without_leaking_the_password(self, mock_session) -> None:
        session = mock_session.return_value
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        session.get.return_value = _json_response(
            {"Data": [_callback_row("open", authed, 1), _callback_row("click", authed, 2)]}
        )

        info = get_external_webhook_info("key", "secret", WEBHOOK_URL)

        assert info.exists is True
        assert info.enabled_events == ["click", "open"]
        assert info.url == WEBHOOK_URL
        assert "stored-password" not in (info.url or "")

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_asks_for_more_than_mailjets_default_page(self, mock_session) -> None:
        # Mailjet returns 10 callback URLs by default. An account with its own callbacks would
        # push ours off that page and every match would come back empty.
        session = mock_session.return_value
        session.get.return_value = _json_response({"Data": []})

        get_external_webhook_info("key", "secret", WEBHOOK_URL)

        assert session.get.call_args.kwargs["params"]["Limit"] > 10

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_reports_missing_when_nothing_points_at_us(self, mock_session) -> None:
        session = mock_session.return_value
        session.get.return_value = _json_response({"Data": [_callback_row("open", "https://example.com/hook")]})

        assert get_external_webhook_info("key", "secret", WEBHOOK_URL).exists is False


class TestDeleteWebhook:
    @mock.patch(MAILJET_SESSION_PATCH)
    def test_deletes_only_our_callback_urls(self, mock_session) -> None:
        session = mock_session.return_value
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        session.get.return_value = _json_response(
            {"Data": [_callback_row("open", authed, 1), _callback_row("click", "https://example.com/hook", 2)]}
        )
        session.delete.return_value = _json_response({}, 200)

        result = delete_webhook("key", "secret", WEBHOOK_URL)

        assert result.success is True
        deleted = [call.args[0] for call in session.delete.call_args_list]
        assert deleted == [f"{MAILJET_BASE_URL}{WEBHOOK_PATH}/1"]

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_reports_a_refused_delete(self, mock_session) -> None:
        session = mock_session.return_value
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        session.get.return_value = _json_response({"Data": [_callback_row("open", authed, 1)]})
        session.delete.return_value = _json_response({}, 403)

        result = delete_webhook("key", "secret", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None


class TestWebhookTableTransformer:
    def test_keeps_the_last_row_per_event_id(self) -> None:
        # Delta merge only dedupes across syncs, so a batch carrying the same delivery twice
        # would otherwise seed duplicate rows on the very first sync.
        import pyarrow as pa

        table = pa.Table.from_pylist(
            [
                {"event_id": "a", "event": "open", "time": 1},
                {"event_id": "b", "event": "click", "time": 2},
                {"event_id": "a", "event": "open", "time": 1},
            ]
        )

        result = _webhook_table_transformer(table).to_pylist()

        assert sorted(row["event_id"] for row in result) == ["a", "b"]

    def test_rows_without_an_event_id_are_kept(self) -> None:
        import pyarrow as pa

        table = pa.Table.from_pylist([{"event_id": None, "event": "open"}, {"event_id": "a", "event": "click"}])

        assert len(_webhook_table_transformer(table).to_pylist()) == 2


class TestWebhookOnlySource:
    def _manager(self, enabled: bool) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.webhook_enabled = mock.AsyncMock(return_value=enabled)
        return manager

    def test_reads_webhook_rows_with_the_dedupe_transformer(self) -> None:
        manager = self._manager(enabled=True)

        response = _source(WEBHOOK_TABLE_NAME, _make_manager(), webhook_source_manager=manager)
        response.items()

        assert response.name == WEBHOOK_TABLE_NAME
        assert response.primary_keys == ["event_id"]
        # Marks the poll as backfill-free, so a reset resumes ingestion rather than wiping rows
        # that no poll could rebuild.
        assert response.webhook_only is True
        manager.webhook_enabled.assert_awaited_once_with(webhook_only=True)
        assert manager.get_items.call_args.kwargs["table_transformer"] is _webhook_table_transformer

    def test_yields_nothing_until_the_webhook_is_registered(self) -> None:
        manager = self._manager(enabled=False)

        response = _source(WEBHOOK_TABLE_NAME, _make_manager(), webhook_source_manager=manager)

        assert list(response.items()) == []
        manager.get_items.assert_not_called()
