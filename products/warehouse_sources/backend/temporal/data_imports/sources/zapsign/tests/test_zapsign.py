import json
import datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from unittest import mock
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.settings import (
    DOCUMENTS_RESOURCE,
    SIGNERS_RESOURCE,
    TEMPLATES_RESOURCE,
    ZAPSIGN_BASE_URL,
    ZAPSIGN_SANDBOX_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.zapsign import (
    ZapSignResumeConfig,
    _to_created_from,
    _webhook_table_transformer,
    base_url_for_environment,
    create_webhook,
    delete_webhook,
    validate_credentials,
    zapsign_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source"
    ".rest_client.make_tracked_session"
)
# Direct-session calls (credential validation, webhook management) build theirs in the zapsign module.
ZAPSIGN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.zapsign.make_tracked_session"
)


def _json_response(payload: dict | list, url: str = f"{ZAPSIGN_BASE_URL}/api/v1/docs/") -> Response:
    response = Response()
    response.status_code = 200
    response.url = url
    response._content = json.dumps(payload).encode()
    return response


def _page(results: list[dict[str, Any]], next_url: str | None = None) -> Response:
    return _json_response({"count": len(results), "next": next_url, "previous": None, "results": results})


def _manager(resume: ZapSignResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _webhook_manager(enabled: bool = False) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.webhook_enabled = mock.AsyncMock(return_value=enabled)
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[requests.PreparedRequest]:
    """Wire a mock session; capture each request AT PREPARE TIME as a real PreparedRequest.

    Preparing with a real session applies the framework auth and encodes params exactly as they'd
    go on the wire, so tests can assert the outgoing URL and Authorization header.
    """
    session.headers = {}
    real = requests.Session()
    prepared: list[requests.PreparedRequest] = []

    def _prepare(request: Any) -> requests.PreparedRequest:
        p = real.prepare_request(request)
        prepared.append(p)
        return p

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return prepared


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    endpoint: str,
    responses: list[Response],
    manager: mock.MagicMock,
    *,
    environment: str | None = "production",
    webhook_manager: mock.MagicMock | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[Any, list[dict[str, Any]], list[requests.PreparedRequest]]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        prepared = _wire(session, responses)
        source_response = zapsign_source(
            api_token="token-123",
            environment=environment,
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
            webhook_source_manager=webhook_manager or _webhook_manager(),
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        )
        rows = _rows(source_response)
    return source_response, rows, prepared


def _query(prepared: requests.PreparedRequest) -> dict[str, list[str]]:
    return parse_qs(urlsplit(cast("str", prepared.url)).query)


class TestBaseUrlForEnvironment:
    @parameterized.expand(
        [
            ("production", "production", ZAPSIGN_BASE_URL),
            ("sandbox", "sandbox", ZAPSIGN_SANDBOX_BASE_URL),
            ("unset", None, ZAPSIGN_BASE_URL),
        ]
    )
    def test_maps_environment_to_host(self, _name: str, environment: str | None, expected: str) -> None:
        assert base_url_for_environment(environment) == expected


class TestToCreatedFrom:
    @parameterized.expand(
        [
            ("datetime", datetime.datetime(2026, 5, 1, 12, 30, 45), "2026-05-01"),
            ("date", datetime.date(2026, 5, 1), "2026-05-01"),
            ("iso_string", "2026-05-01T12:30:45Z", "2026-05-01"),
            ("none", None, None),
        ]
    )
    def test_formats_watermark_as_date(self, _name: str, value: Any, expected: str | None) -> None:
        assert _to_created_from(value) == expected


class TestDocumentsSource:
    def test_paginates_via_next_link_and_yields_rows(self) -> None:
        page2_url = f"{ZAPSIGN_BASE_URL}/api/v1/docs/?page=2"
        responses = [
            _page([{"token": "d1", "created_at": "2026-01-01T00:00:00Z"}], next_url=page2_url),
            _page([{"token": "d2", "created_at": "2026-01-02T00:00:00Z"}]),
        ]
        _, rows, prepared = _run(DOCUMENTS_RESOURCE, responses, _manager())

        assert [row["token"] for row in rows] == ["d1", "d2"]
        assert len(prepared) == 2
        first_url = cast("str", prepared[0].url)
        assert first_url.startswith(f"{ZAPSIGN_BASE_URL}/api/v1/docs/")
        assert cast("str", prepared[1].url) == page2_url

    def test_first_request_sends_stable_sort_and_signers_and_bearer_auth(self) -> None:
        _, _, prepared = _run(DOCUMENTS_RESOURCE, [_page([])], _manager())

        query = _query(prepared[0])
        assert query["sort_order"] == ["asc"]
        assert query["include_signers"] == ["true"]
        assert prepared[0].headers["Authorization"] == "Bearer token-123"

    def test_incremental_sends_created_from_date(self) -> None:
        _, _, prepared = _run(
            DOCUMENTS_RESOURCE,
            [_page([])],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.datetime(2026, 5, 1, 12, 30),
        )

        assert _query(prepared[0])["created_from"] == ["2026-05-01"]

    def test_full_refresh_omits_created_from(self) -> None:
        _, _, prepared = _run(DOCUMENTS_RESOURCE, [_page([])], _manager())

        assert "created_from" not in _query(prepared[0])

    def test_sandbox_environment_targets_sandbox_host(self) -> None:
        _, _, prepared = _run(
            DOCUMENTS_RESOURCE,
            [_json_response({"count": 0, "next": None, "previous": None, "results": []})],
            _manager(),
            environment="sandbox",
        )

        assert cast("str", prepared[0].url).startswith(f"{ZAPSIGN_SANDBOX_BASE_URL}/api/v1/docs/")

    def test_source_response_metadata(self) -> None:
        source_response, _, _ = _run(DOCUMENTS_RESOURCE, [_page([])], _manager())

        assert source_response.name == DOCUMENTS_RESOURCE
        assert source_response.primary_keys == ["token"]
        assert source_response.sort_mode == "asc"
        assert source_response.partition_keys == ["created_at"]
        assert source_response.partition_mode == "datetime"

    def test_saves_resume_state_after_page_and_not_on_terminal_page(self) -> None:
        page2_url = f"{ZAPSIGN_BASE_URL}/api/v1/docs/?page=2"
        manager = _manager()
        _run(DOCUMENTS_RESOURCE, [_page([{"token": "d1"}], next_url=page2_url), _page([{"token": "d2"}])], manager)

        # One save (after the first page, pointing at page 2); the terminal page saves nothing.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert saved == ZapSignResumeConfig(endpoint=DOCUMENTS_RESOURCE, paginator_state={"next_url": page2_url})

    def test_resumes_from_saved_next_url(self) -> None:
        page2_url = f"{ZAPSIGN_BASE_URL}/api/v1/docs/?page=2"
        resume = ZapSignResumeConfig(endpoint=DOCUMENTS_RESOURCE, paginator_state={"next_url": page2_url})
        _, rows, prepared = _run(DOCUMENTS_RESOURCE, [_page([{"token": "d2"}])], _manager(resume))

        assert [row["token"] for row in rows] == ["d2"]
        assert cast("str", prepared[0].url) == page2_url

    def test_ignores_resume_state_saved_by_a_different_endpoint(self) -> None:
        resume = ZapSignResumeConfig(
            endpoint=TEMPLATES_RESOURCE, paginator_state={"next_url": f"{ZAPSIGN_BASE_URL}/api/v1/templates/?page=9"}
        )
        _, _, prepared = _run(DOCUMENTS_RESOURCE, [_page([])], _manager(resume))

        assert cast("str", prepared[0].url).startswith(f"{ZAPSIGN_BASE_URL}/api/v1/docs/")

    def test_webhook_mode_reads_buffered_deliveries_instead_of_polling(self) -> None:
        webhook_manager = _webhook_manager(enabled=True)
        sentinel = object()
        webhook_manager.get_items.return_value = sentinel

        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            _wire(MockSession.return_value, [])
            source_response = zapsign_source(
                api_token="token-123",
                environment="production",
                endpoint=DOCUMENTS_RESOURCE,
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_manager(),
                webhook_source_manager=webhook_manager,
                db_incremental_field_last_value=None,
            )

        assert source_response.items() is sentinel
        webhook_manager.get_items.assert_called_once_with(table_transformer=_webhook_table_transformer)


class TestTemplatesSource:
    def test_yields_rows_and_metadata(self) -> None:
        responses = [_page([{"token": "t1", "name": "NDA", "created_at": "2026-01-01T00:00:00Z"}])]
        source_response, rows, prepared = _run(TEMPLATES_RESOURCE, responses, _manager())

        assert [row["token"] for row in rows] == ["t1"]
        assert cast("str", prepared[0].url).startswith(f"{ZAPSIGN_BASE_URL}/api/v1/templates/")
        assert source_response.primary_keys == ["token"]
        assert source_response.partition_keys == ["created_at"]


class TestSignersSource:
    def test_fans_out_to_document_detail_and_injects_parent_token(self) -> None:
        responses = [
            _page([{"token": "d1"}, {"token": "d2"}]),
            _json_response({"token": "d1", "signers": [{"token": "s1", "status": "signed"}]}),
            _json_response({"token": "d2", "signers": [{"token": "s2", "status": "new"}, {"token": "s3"}]}),
        ]
        source_response, rows, prepared = _run(SIGNERS_RESOURCE, responses, _manager())

        assert [(row["_documents_token"], row["token"]) for row in rows] == [
            ("d1", "s1"),
            ("d2", "s2"),
            ("d2", "s3"),
        ]
        assert cast("str", prepared[1].url).startswith(f"{ZAPSIGN_BASE_URL}/api/v1/docs/d1/")
        assert cast("str", prepared[2].url).startswith(f"{ZAPSIGN_BASE_URL}/api/v1/docs/d2/")
        # Composite key: signer tokens aren't documented as globally unique.
        assert source_response.primary_keys == ["_documents_token", "token"]
        assert source_response.partition_keys is None


class TestWebhookTableTransformer:
    def test_keeps_latest_row_per_document_and_drops_event_fields(self) -> None:
        table = table_from_py_list(
            [
                {
                    "token": "d1",
                    "status": "pending",
                    "event_type": "doc_created",
                    "signer_who_signed": {"token": "s1"},
                    "created_at": "2026-01-01T00:00:00Z",
                    "last_update_at": "2026-01-01T00:00:00Z",
                },
                {
                    "token": "d1",
                    "status": "signed",
                    "event_type": "doc_signed",
                    "signer_who_signed": {"token": "s1"},
                    "created_at": "2026-01-01T00:00:00Z",
                    "last_update_at": "2026-01-02T00:00:00Z",
                },
                {
                    "token": "d2",
                    "status": "pending",
                    "event_type": "doc_created",
                    "signer_who_signed": None,
                    "created_at": "2026-01-03T00:00:00Z",
                    "last_update_at": "2026-01-03T00:00:00Z",
                },
            ]
        )

        result = _webhook_table_transformer(table)
        rows = {row["token"]: row for row in result.to_pylist()}

        assert rows["d1"]["status"] == "signed"
        assert rows["d2"]["status"] == "pending"
        assert "event_type" not in result.column_names
        assert "signer_who_signed" not in result.column_names

    def test_parses_timestamps_and_skips_rows_without_token(self) -> None:
        table = table_from_py_list(
            [
                {"token": "d1", "created_at": "2026-01-01T00:00:00Z", "last_update_at": "not-a-date"},
                {"token": None, "created_at": "2026-01-01T00:00:00Z"},
            ]
        )

        result = _webhook_table_transformer(table)
        rows = result.to_pylist()

        assert len(rows) == 1
        assert rows[0]["created_at"] == datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        assert rows[0]["last_update_at"] is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("forbidden", 403, False, "rejected the API token"),
            ("unauthorized", 401, False, "rejected the API token"),
            ("server_error", 500, False, "unexpected status (500)"),
        ]
    )
    @patch(ZAPSIGN_SESSION_PATCH)
    def test_maps_status_codes(
        self, _name: str, status_code: int, expected_ok: bool, expected_error: str | None, mock_session: MagicMock
    ) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        ok, error = validate_credentials("token-123", "production")

        assert ok is expected_ok
        if expected_error is None:
            assert error is None
        else:
            assert expected_error in cast("str", error)

    @patch(ZAPSIGN_SESSION_PATCH)
    def test_returns_false_on_network_error(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("dns fail")

        ok, error = validate_credentials("token-123", "production")

        assert ok is False
        assert "Could not reach ZapSign" in cast("str", error)

    @patch(ZAPSIGN_SESSION_PATCH)
    def test_probes_the_documents_list_on_the_selected_host(self, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("token-123", "sandbox")

        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{ZAPSIGN_SANDBOX_BASE_URL}/api/v1/docs/"


class TestCreateWebhook:
    @patch(ZAPSIGN_SESSION_PATCH)
    def test_registers_all_document_events_with_generated_auth_header(self, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        mock_session.return_value.post.return_value = response

        result = create_webhook("token-123", "production", "https://webhooks.posthog.com/dwh/abc")

        assert result.success is True
        called = mock_session.return_value.post.call_args
        assert called.args[0] == f"{ZAPSIGN_BASE_URL}/api/v1/user/company/webhook/"
        body = called.kwargs["json"]
        assert body["url"] == "https://webhooks.posthog.com/dwh/abc"
        assert body["type"] == ""
        header = body["headers"][0]
        assert header["name"] == "Authorization"
        assert header["value"].startswith("Bearer ")
        # The generated header value is handed back so the Hog template can verify deliveries.
        assert result.extra_inputs == {"authorization_header": header["value"]}

    @parameterized.expand(
        [
            ("forbidden", 403, "rejected the API token"),
            ("server_error", 500, "ZapSign API error (500)"),
        ]
    )
    @patch(ZAPSIGN_SESSION_PATCH)
    def test_reports_http_errors(
        self, _name: str, status_code: int, expected_error: str, mock_session: MagicMock
    ) -> None:
        response = MagicMock()
        response.status_code = status_code
        http_error = requests.HTTPError(response=response)
        response.raise_for_status.side_effect = http_error
        mock_session.return_value.post.return_value = response

        result = create_webhook("token-123", "production", "https://webhooks.posthog.com/dwh/abc")

        assert result.success is False
        assert expected_error in cast("str", result.error)

    @patch(ZAPSIGN_SESSION_PATCH)
    def test_reports_network_errors(self, mock_session: MagicMock) -> None:
        mock_session.return_value.post.side_effect = requests.ConnectionError("dns fail")

        result = create_webhook("token-123", "production", "https://webhooks.posthog.com/dwh/abc")

        assert result.success is False
        assert "Could not reach ZapSign" in cast("str", result.error)


class TestDeleteWebhook:
    def test_reports_manual_deletion_required(self) -> None:
        result = delete_webhook()

        assert result.success is False
        assert "Delete it in ZapSign" in cast("str", result.error)
