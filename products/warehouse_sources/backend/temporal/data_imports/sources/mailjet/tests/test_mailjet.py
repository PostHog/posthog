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
    create_webhook,
    delete_webhook,
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


class TestOffsetPagination:
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


WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hog-fn-1"


def _callback_row(event: str, url: str, row_id: int = 1, status: str = "alive") -> dict[str, Any]:
    return {"ID": row_id, "EventType": event, "Url": url, "Status": status, "Version": 1, "IsBackup": False}


def _json_response(body: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    return response


class TestCreateWebhook:
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
