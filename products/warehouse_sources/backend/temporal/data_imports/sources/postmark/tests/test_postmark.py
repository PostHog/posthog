import json
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postmark import (
    PostmarkSourceConfig,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source import PostmarkSource

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# Webhook management builds its session through a module-level helper in the postmark module.
POSTMARK_LOGGER_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.logger"


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


def _run(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(PostmarkSource(), PostmarkSourceConfig(server_token="test-token")).run(
        endpoint, script, **inputs
    )


def _list_response(endpoint: str, rows: list[dict[str, Any]] | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={POSTMARK_ENDPOINTS[endpoint].data_key: rows or [], "TotalCount": len(rows or [])})


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok_200", 200, True),
            ("unauthorized_401", 401, False),
            ("forbidden_403", 403, False),
            ("server_500", 500, False),
        ]
    )
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool):
        # A 500 is retried by the real request stack, so every try gets the same answer.
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            # The status flows back to the caller so it can distinguish rejection causes.
            assert validate_credentials("test-token") == (expected, status_code)

        # The probe session masks the token by value so it never lands in a captured HTTP sample.
        assert network.session_options[0]["redact_values"] == ("test-token",)
        # The token is carried in the X-Postmark-Server-Token header against /message-streams.
        request = network.requests_log[0]
        assert request.url == f"{POSTMARK_BASE_URL}/message-streams"
        assert request.headers["x-postmark-server-token"] == "test-token"


class TestOffsetPagination:
    def test_resumes_from_saved_offset(self):
        result = _run(
            "messages_outbound",
            [ScriptedResponse(json={"TotalCount": 501, "Messages": [{"MessageID": "m501"}]})],
            resume_state=PostmarkResumeConfig(next_offset=500),
        )

        assert result.params("offset")[0] == "500"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self):
        result = _run("messages_outbound", [_list_response("messages_outbound")])

        assert result.params("offset")[0] == "0"

    @mock.patch(POSTMARK_LOGGER_PATCH)
    def test_stops_at_10k_window_and_warns(self, mock_logger):
        # Every page is full, so pagination would continue forever if not for the window cap.
        full_page = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500)]

        result = _run(
            "messages_outbound",
            lambda _request: ScriptedResponse(json={"TotalCount": 99999, "Messages": full_page}),
        )

        # 10,000 / 500 = 20 pages, then the loop terminates at the window boundary.
        assert len(result.requests) == POSTMARK_MAX_WINDOW // 500
        mock_logger.warning.assert_called_once()
        last = result.requests[-1]
        assert int(last.param("offset") or 0) + int(last.param("count") or 0) == POSTMARK_MAX_WINDOW


class TestEndpointDataKeys:
    @parameterized.expand(
        [
            ("messages_outbound", "Messages", "MessageID"),
            ("messages_inbound", "InboundMessages", "MessageID"),
            ("opens", "Opens", "MessageID"),
            ("templates", "Templates", "TemplateId"),
            ("message_streams", "MessageStreams", "ID"),
            ("bounces", "Bounces", "ID"),
        ]
    )
    def test_reads_correct_data_key(self, endpoint: str, data_key: str, primary_key: str):
        result = _run(endpoint, [ScriptedResponse(json={data_key: [{primary_key: "x1"}], "TotalCount": 1})])

        assert [r[primary_key] for r in result.rows] == ["x1"]


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str):
        response = _run(endpoint, [_list_response(endpoint)]).response

        assert response is not None
        self._assert_shape(endpoint, response)

    @staticmethod
    def _assert_shape(endpoint: str, response: Any) -> None:
        config = POSTMARK_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys

        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestRetryable:
    def test_401_does_not_retry_and_raises(self):
        result = _run("message_streams", [ScriptedResponse(status=401, json={})])

        assert result.raised is not None
        assert len(result.requests) == 1


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

    @parameterized.expand([(name,) for name in ENDPOINTS if name not in WEBHOOK_SCHEMA_NAMES])
    def test_non_webhook_endpoints_never_consult_the_webhook_manager(self, endpoint: str):
        # Only bounces has a matching Postmark trigger; the rest must keep polling regardless
        # of whether a webhook function exists for the source. Consulting the manager would read
        # the database, which the driver blocks, so a clean run shows it was never consulted.
        result = _run(endpoint, [_list_response(endpoint, [{POSTMARK_ENDPOINTS[endpoint].primary_keys[0]: "x1"}])])

        assert result.raised is None
        assert len(result.rows) == 1


class TestWebhookManagement:
    def test_create_webhook_subscribes_bounce_triggers_with_a_secret_header(self):
        with scripted_network(
            [
                ScriptedResponse(json={"Webhooks": []}),
                ScriptedResponse(json={"ID": 42, "Url": "https://ph.example/webhook"}),
            ]
        ) as network:
            result = create_webhook("test-token", "https://ph.example/webhook")

        assert result.success is True
        secret = result.extra_inputs["signing_secret"]
        assert secret
        assert [request.method for request in network.requests_log] == ["GET", "POST"]
        body = network.requests_log[1].json()
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
        assert network.session_options[0]["capture"] is False
        assert network.session_options[0]["redact_values"] == ("test-token",)

    def test_create_webhook_updates_an_existing_url_instead_of_duplicating(self):
        with scripted_network(
            [
                ScriptedResponse(json={"Webhooks": [{"ID": 7, "Url": "https://ph.example/webhook"}]}),
                ScriptedResponse(json={"ID": 7, "Url": "https://ph.example/webhook"}),
            ]
        ) as network:
            result = create_webhook("test-token", "https://ph.example/webhook")

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET", "PUT"]
        assert network.requests_log[1].url == f"{POSTMARK_BASE_URL}/webhooks/7"

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_create_webhook_surfaces_a_token_problem(self, _name: str, status: int):
        with scripted_network([ScriptedResponse(json={"Webhooks": []}), ScriptedResponse(status=status, json={})]):
            result = create_webhook("test-token", "https://ph.example/webhook")

        assert result.success is False
        assert result.error == WEBHOOK_AUTH_ERROR

    def test_create_webhook_treats_a_200_with_an_error_code_as_a_failure(self):
        # Postmark reports API failures in the body, so response.ok alone would report success.
        with scripted_network(
            [
                ScriptedResponse(json={"Webhooks": []}),
                ScriptedResponse(json={"ErrorCode": 401, "Message": "Not allowed"}),
            ]
        ):
            result = create_webhook("test-token", "https://ph.example/webhook")

        assert result.success is False
        assert "Not allowed" in (result.error or "")

    def test_get_external_webhook_info_reports_enabled_triggers(self):
        with scripted_network(
            [
                ScriptedResponse(
                    json={
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
            ]
        ):
            info = get_external_webhook_info("test-token", "https://ph.example/webhook")

        assert info.exists is True
        assert info.url == "https://ph.example/webhook"
        assert set(info.enabled_events or []) == {"Bounce", "SpamComplaint"}

    def test_get_external_webhook_info_ignores_other_urls(self):
        with scripted_network(
            [ScriptedResponse(json={"Webhooks": [{"ID": 7, "Url": "https://someone-else.example/hook"}]})]
        ):
            info = get_external_webhook_info("test-token", "https://ph.example/webhook")

        assert info.exists is False
        assert info.error is None

    def test_delete_webhook_removes_the_matching_webhook(self):
        with scripted_network(
            [
                ScriptedResponse(json={"Webhooks": [{"ID": 7, "Url": "https://ph.example/webhook"}]}),
                ScriptedResponse(json={"ErrorCode": 0, "Message": "Webhook 7 removed."}),
            ]
        ) as network:
            result = delete_webhook("test-token", "https://ph.example/webhook")

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET", "DELETE"]
        assert network.requests_log[1].url == f"{POSTMARK_BASE_URL}/webhooks/7"

    def test_delete_webhook_is_idempotent_when_already_gone(self):
        with scripted_network([ScriptedResponse(json={"Webhooks": []})]) as network:
            result = delete_webhook("test-token", "https://ph.example/webhook")

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET"]

    def test_delete_webhook_reports_a_failure(self):
        with scripted_network(
            [
                ScriptedResponse(json={"Webhooks": [{"ID": 7, "Url": "https://ph.example/webhook"}]}),
                ScriptedResponse(status=422, json={"ErrorCode": 501, "Message": "Webhook not found."}),
            ]
        ):
            result = delete_webhook("test-token", "https://ph.example/webhook")

        assert result.success is False
        assert "Webhook not found." in (result.error or "")
