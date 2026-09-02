import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark import (
    POSTMARK_BASE_URL,
    WEBHOOK_AUTH_ERROR,
    PostmarkResumeConfig,
    _webhook_table_transformer,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    postmark_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import (
    ENDPOINTS,
    POSTMARK_ENDPOINTS,
    POSTMARK_MAX_WINDOW,
    WEBHOOK_MESSAGE_STREAM,
    WEBHOOK_SCHEMA_NAMES,
    WEBHOOK_SECRET_HEADER,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the postmark module.
POSTMARK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session"
)
# Webhook management builds its session through the same module-level helper.
WEBHOOK_SESSION_PATCH = POSTMARK_SESSION_PATCH


def _response(body: dict[str, Any], *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = POSTMARK_BASE_URL
    return resp


def _make_manager(resume_state: PostmarkResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response] | Any) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when
    each request is prepared rather than inspecting the final mutated state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return postmark_source("test-token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok_200", 200, True),
            ("unauthorized_401", 401, False),
            ("forbidden_403", 403, False),
            ("server_500", 500, False),
        ]
    )
    @mock.patch(POSTMARK_SESSION_PATCH)
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool, mock_session: mock.MagicMock):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        # The status flows back to the caller so it can distinguish rejection causes.
        assert validate_credentials("test-token") == (expected, status_code)

        # The probe session masks the token by value so it never lands in a captured HTTP sample.
        assert mock_session.call_args.kwargs["redact_values"] == ("test-token",)
        # The token is carried in the X-Postmark-Server-Token header against /message-streams.
        get_args, get_kwargs = mock_session.return_value.get.call_args
        assert get_args[0] == f"{POSTMARK_BASE_URL}/message-streams"
        assert get_kwargs["headers"]["X-Postmark-Server-Token"] == "test-token"

    @mock.patch(POSTMARK_SESSION_PATCH)
    def test_validate_credentials_network_error_returns_none_status(self, mock_session: mock.MagicMock):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("test-token") == (False, None)


class TestFlatEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_message_streams_yields_single_batch(self, MockSession):
        session = MockSession.return_value
        rows_in = [{"ID": "outbound", "Name": "Transactional", "CreatedAt": "2026-01-01T00:00:00Z"}]
        params = _wire(session, [_response({"MessageStreams": rows_in})])

        rows = _rows(_source("message_streams", _make_manager()))

        assert [r["ID"] for r in rows] == ["outbound"]
        assert session.send.call_count == 1
        # The sync session masks the token by value to keep it out of captured HTTP samples.
        assert MockSession.call_args.kwargs["redact_values"] == ("test-token",)
        # Flat endpoints fetch with no pagination params.
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flat_endpoint_empty_response_yields_nothing(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"MessageStreams": []})])

        assert _rows(_source("message_streams", _make_manager())) == []


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page_and_saves_state(self, MockSession):
        session = MockSession.return_value
        page1 = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500)]
        page2 = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500, 510)]
        params = _wire(
            session,
            [
                _response({"TotalCount": 510, "Messages": page1}),
                _response({"TotalCount": 510, "Messages": page2}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("messages_outbound", manager))

        assert len(rows) == 510
        assert session.send.call_count == 2
        assert params[0]["offset"] == 0 and params[0]["count"] == 500
        assert params[1]["offset"] == 500

        # State is saved once, after the first (full) page, pointing at the next offset.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == PostmarkResumeConfig(next_offset=500)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_does_not_save_state(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"TotalCount": 1, "Messages": [{"MessageID": "m1"}]})])

        manager = _make_manager()
        rows = _rows(_source("messages_outbound", manager))

        assert len(rows) == 1
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response({"TotalCount": 501, "Messages": [{"MessageID": "m501"}]})])

        manager = _make_manager(PostmarkResumeConfig(next_offset=500))
        _rows(_source("messages_outbound", manager))

        assert params[0]["offset"] == 500

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.logger")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_10k_window_and_warns(self, MockSession, mock_logger):
        session = MockSession.return_value
        # Every page is full, so pagination would continue forever if not for the window cap.
        full_page = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500)]
        params = _wire(session, lambda *a, **k: _response({"TotalCount": 99999, "Messages": full_page}))

        _rows(_source("messages_outbound", _make_manager()))

        # 10,000 / 500 = 20 pages, then the loop terminates at the window boundary.
        assert session.send.call_count == POSTMARK_MAX_WINDOW // 500
        mock_logger.warning.assert_called_once()
        assert params[-1]["offset"] + params[-1]["count"] == POSTMARK_MAX_WINDOW


class TestEndpointDataKeys:
    @parameterized.expand(
        [
            ("messages_outbound", "Messages", "MessageID"),
            ("messages_inbound", "InboundMessages", "MessageID"),
            ("bounces", "Bounces", "ID"),
            ("templates", "Templates", "TemplateId"),
            ("message_streams", "MessageStreams", "ID"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_correct_data_key(self, endpoint: str, data_key: str, primary_key: str, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({data_key: [{primary_key: "x1"}], "TotalCount": 1})])

        rows = _rows(_source(endpoint, _make_manager()))

        assert [r[primary_key] for r in rows] == ["x1"]


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, _MockSession):
        response = _source(endpoint, _make_manager())

        config = POSTMARK_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]

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
    def test_429_retries_until_success(self, MockSession, _mock_sleep):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status=429),
                _response({"MessageStreams": [{"ID": "outbound"}]}),
            ],
        )

        rows = _rows(_source("message_streams", _make_manager()))

        assert [r["ID"] for r in rows] == ["outbound"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_401_does_not_retry_and_raises(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({}, status=401)])

        with pytest.raises(Exception):
            _rows(_source("message_streams", _make_manager()))

        assert session.send.call_count == 1


def _bounce(bounce_id: int, **overrides: Any) -> dict[str, Any]:
    return {
        "RecordType": "Bounce",
        "ID": bounce_id,
        "Type": "HardBounce",
        "TypeCode": 1,
        "MessageID": "883953f4-6105-42a2-a16a-77a8eac79483",
        "Email": "john@example.com",
        "BouncedAt": "2026-01-01T00:00:00.0000000Z",
        "Inactive": True,
        **overrides,
    }


class TestWebhookTableTransformer:
    def test_drops_webhook_only_fields_so_rows_match_the_pull_shape(self):
        # Metadata holds arbitrary user keys; keeping it would evolve the table schema on every
        # new key a customer sets, and neither field exists in the Bounce API list response.
        table = table_from_py_list([_bounce(1, Metadata={"plan": "pro"}, Content="<dump>")])

        rows = _webhook_table_transformer(table).to_pylist()

        assert len(rows) == 1
        assert "Metadata" not in rows[0]
        assert "Content" not in rows[0]
        assert rows[0]["ID"] == 1

    def test_keeps_the_latest_row_per_id_within_a_batch(self):
        # Delta merge only dedupes across syncs, so a redelivery inside one batch has to
        # collapse here or the merge multi-matches on ID.
        table = table_from_py_list(
            [
                _bounce(1, BouncedAt="2026-01-01T00:00:00.0000000Z", Inactive=True),
                _bounce(2, BouncedAt="2026-01-02T00:00:00.0000000Z"),
                _bounce(1, BouncedAt="2026-01-03T00:00:00.0000000Z", Inactive=False),
            ]
        )

        rows = {row["ID"]: row for row in _webhook_table_transformer(table).to_pylist()}

        assert len(rows) == 2
        assert rows[1]["Inactive"] is False
        assert rows[1]["BouncedAt"] == "2026-01-03T00:00:00.0000000Z"

    @parameterized.expand(
        [
            ("unparseable_timestamp", "not-a-date"),
            ("missing_timestamp", None),
        ]
    )
    def test_falls_back_to_arrival_order_when_the_timestamp_is_unusable(self, _name: str, bounced_at: Any):
        table = table_from_py_list(
            [
                _bounce(1, BouncedAt=bounced_at, Inactive=True),
                _bounce(1, BouncedAt=bounced_at, Inactive=False),
            ]
        )

        rows = _webhook_table_transformer(table).to_pylist()

        assert len(rows) == 1
        assert rows[0]["Inactive"] is False

    def test_drops_rows_without_an_id(self):
        # ID is the merge key, so a row without one would land unmergeable.
        table = table_from_py_list([_bounce(1), {**_bounce(2), "ID": None}])

        rows = _webhook_table_transformer(table).to_pylist()

        assert [row["ID"] for row in rows] == [1]


class TestWebhookItemsWiring:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bounces_reads_pushed_rows_once_the_webhook_is_live(self, MockSession):
        _wire(MockSession.return_value, [_response({"Bounces": [_bounce(1)], "TotalCount": 1})])
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)
        webhook_manager.get_items.return_value = iter([[_bounce(9)]])

        response = postmark_source(
            "test-token",
            "bounces",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
            webhook_source_manager=webhook_manager,
        )
        rows = _rows(response)

        assert [row["ID"] for row in rows] == [9]
        assert MockSession.return_value.send.call_count == 0
        # Webhooks only take over after the backfill has completed.
        assert webhook_manager.webhook_enabled.await_args.kwargs == {"webhook_only": False}
        assert webhook_manager.get_items.call_args.kwargs["table_transformer"] is _webhook_table_transformer

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bounces_falls_back_to_the_pull_api_when_no_webhook_is_live(self, MockSession):
        _wire(MockSession.return_value, [_response({"Bounces": [_bounce(1)], "TotalCount": 1})])
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=False)

        rows = _rows(
            postmark_source(
                "test-token",
                "bounces",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                webhook_source_manager=webhook_manager,
            )
        )

        assert [row["ID"] for row in rows] == [1]
        webhook_manager.get_items.assert_not_called()

    @parameterized.expand([(name,) for name in ENDPOINTS if name not in WEBHOOK_SCHEMA_NAMES])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_webhook_endpoints_never_consult_the_webhook_manager(self, endpoint: str, MockSession):
        # Only bounces has a matching Postmark trigger; the rest must keep polling regardless
        # of whether a webhook function exists for the source.
        _wire(MockSession.return_value, lambda *a, **k: _response({POSTMARK_ENDPOINTS[endpoint].data_key: []}))
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        _rows(
            postmark_source(
                "test-token",
                endpoint,
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                webhook_source_manager=webhook_manager,
            )
        )

        webhook_manager.webhook_enabled.assert_not_awaited()
        webhook_manager.get_items.assert_not_called()


class TestWebhookManagement:
    @mock.patch(WEBHOOK_SESSION_PATCH)
    def test_create_webhook_subscribes_bounce_triggers_with_a_secret_header(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _response({"Webhooks": []})
        session.post.return_value = _response({"ID": 42, "Url": "https://ph.example/webhook"})

        result = create_webhook("test-token", "https://ph.example/webhook")

        assert result.success is True
        secret = result.extra_inputs["signing_secret"]
        assert secret
        body = session.post.call_args.kwargs["json"]
        assert body["Url"] == "https://ph.example/webhook"
        assert body["MessageStream"] == WEBHOOK_MESSAGE_STREAM
        # Postmark signs nothing, so the shared secret header is the only proof of origin.
        assert body["HttpHeaders"] == [{"Name": WEBHOOK_SECRET_HEADER, "Value": secret}]
        # Bounce alone would leave spam complaints unsynced once webhooks take over polling.
        assert {name for name, trigger in body["Triggers"].items() if trigger["Enabled"]} == {
            "Bounce",
            "SpamComplaint",
        }
        assert all(not trigger["IncludeContent"] for trigger in body["Triggers"].values())
        # Webhook objects echo the secret back, so they stay out of HTTP sample capture.
        assert mock_session.call_args.kwargs["capture"] is False
        assert mock_session.call_args.kwargs["redact_values"] == ("test-token",)

    @mock.patch(WEBHOOK_SESSION_PATCH)
    def test_create_webhook_updates_an_existing_url_instead_of_duplicating(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _response({"Webhooks": [{"ID": 7, "Url": "https://ph.example/webhook"}]})
        session.put.return_value = _response({"ID": 7, "Url": "https://ph.example/webhook"})

        result = create_webhook("test-token", "https://ph.example/webhook")

        assert result.success is True
        session.post.assert_not_called()
        assert session.put.call_args.args[0] == f"{POSTMARK_BASE_URL}/webhooks/7"

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    @mock.patch(WEBHOOK_SESSION_PATCH)
    def test_create_webhook_surfaces_a_token_problem(self, _name: str, status: int, mock_session):
        session = mock_session.return_value
        session.get.return_value = _response({"Webhooks": []})
        session.post.return_value = _response({}, status=status)

        result = create_webhook("test-token", "https://ph.example/webhook")

        assert result.success is False
        assert result.error == WEBHOOK_AUTH_ERROR

    @mock.patch(WEBHOOK_SESSION_PATCH)
    def test_create_webhook_treats_a_200_with_an_error_code_as_a_failure(self, mock_session):
        # Postmark reports API failures in the body, so response.ok alone would report success.
        session = mock_session.return_value
        session.get.return_value = _response({"Webhooks": []})
        session.post.return_value = _response({"ErrorCode": 401, "Message": "Not allowed"})

        result = create_webhook("test-token", "https://ph.example/webhook")

        assert result.success is False
        assert "Not allowed" in (result.error or "")

    @mock.patch(WEBHOOK_SESSION_PATCH)
    def test_get_external_webhook_info_reports_enabled_triggers(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            {
                "Webhooks": [
                    {
                        "ID": 7,
                        "Url": "https://ph.example/webhook",
                        "MessageStream": "outbound",
                        "Triggers": {
                            "Bounce": {"Enabled": True},
                            "SpamComplaint": {"Enabled": True},
                            "Open": {"Enabled": False},
                        },
                    }
                ]
            }
        )

        info = get_external_webhook_info("test-token", "https://ph.example/webhook")

        assert info.exists is True
        assert info.url == "https://ph.example/webhook"
        assert set(info.enabled_events or []) == {"Bounce", "SpamComplaint"}

    @mock.patch(WEBHOOK_SESSION_PATCH)
    def test_get_external_webhook_info_ignores_other_urls(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            {"Webhooks": [{"ID": 7, "Url": "https://someone-else.example/hook"}]}
        )

        info = get_external_webhook_info("test-token", "https://ph.example/webhook")

        assert info.exists is False
        assert info.error is None

    @mock.patch(WEBHOOK_SESSION_PATCH)
    def test_delete_webhook_removes_the_matching_webhook(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _response({"Webhooks": [{"ID": 7, "Url": "https://ph.example/webhook"}]})
        session.delete.return_value = _response({"ErrorCode": 0, "Message": "Webhook 7 removed."})

        result = delete_webhook("test-token", "https://ph.example/webhook")

        assert result.success is True
        assert session.delete.call_args.args[0] == f"{POSTMARK_BASE_URL}/webhooks/7"

    @mock.patch(WEBHOOK_SESSION_PATCH)
    def test_delete_webhook_is_idempotent_when_already_gone(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _response({"Webhooks": []})

        result = delete_webhook("test-token", "https://ph.example/webhook")

        assert result.success is True
        session.delete.assert_not_called()

    @mock.patch(WEBHOOK_SESSION_PATCH)
    def test_delete_webhook_reports_a_failure(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _response({"Webhooks": [{"ID": 7, "Url": "https://ph.example/webhook"}]})
        session.delete.return_value = _response({"ErrorCode": 501, "Message": "Webhook not found."}, status=422)

        result = delete_webhook("test-token", "https://ph.example/webhook")

        assert result.success is False
        assert "Webhook not found." in (result.error or "")
