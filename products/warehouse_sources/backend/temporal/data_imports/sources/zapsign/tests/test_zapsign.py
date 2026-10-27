import datetime
from typing import Any, cast

from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zapsign import (
    ZapSignSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.settings import (
    DOCUMENTS_RESOURCE,
    SIGNERS_RESOURCE,
    TEMPLATES_RESOURCE,
    ZAPSIGN_BASE_URL,
    ZAPSIGN_SANDBOX_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.source import ZapSignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.zapsign import (
    ZapSignResumeConfig,
    _to_created_from,
    _webhook_table_transformer,
    base_url_for_environment,
    create_webhook,
    zapsign_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source"
    ".rest_client.make_tracked_session"
)


def _driver() -> SourceDriver:
    return SourceDriver(ZapSignSource(), ZapSignSourceConfig(api_token="token-123", environment="production"))


def _scripted_page(results: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"count": len(results), "next": next_url, "previous": None, "results": results})


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
    def test_incremental_sends_created_from_date(self) -> None:
        result = _driver().run(
            DOCUMENTS_RESOURCE,
            [_scripted_page([])],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime.datetime(2026, 5, 1, 12, 30),
        )

        assert result.params("created_from") == ["2026-05-01"]

    def test_a_full_refresh_sends_no_created_from_date(self) -> None:
        result = _driver().run(
            DOCUMENTS_RESOURCE,
            [_scripted_page([])],
            incremental_field="created_at",
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime.datetime(2026, 5, 1, 12, 30),
        )

        assert result.params("created_from") == [None]

    def test_resumes_from_saved_next_url(self) -> None:
        page2_url = f"{ZAPSIGN_BASE_URL}/api/v1/docs/?page=2"
        result = _driver().run(
            DOCUMENTS_RESOURCE,
            [_scripted_page([{"token": "d2"}])],
            resume_state=ZapSignResumeConfig(endpoint=DOCUMENTS_RESOURCE, paginator_state={"next_url": page2_url}),
        )

        assert [row["token"] for row in result.rows] == ["d2"]
        assert result.urls[0] == page2_url

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
        result = _driver().run(
            TEMPLATES_RESOURCE,
            [_scripted_page([{"token": "t1", "name": "NDA", "created_at": "2026-01-01T00:00:00Z"}])],
        )

        assert [row["token"] for row in result.rows] == ["t1"]
        assert result.urls[0].startswith(f"{ZAPSIGN_BASE_URL}/api/v1/templates/")
        assert result.response is not None
        assert result.response.primary_keys == ["token"]
        assert result.response.partition_keys == ["created_at"]


class TestSignersSource:
    def test_fans_out_to_document_detail_and_injects_parent_token(self) -> None:
        result = _driver().run(
            SIGNERS_RESOURCE,
            [
                _scripted_page([{"token": "d1"}, {"token": "d2"}]),
                ScriptedResponse(json={"token": "d1", "signers": [{"token": "s1", "status": "signed"}]}),
                ScriptedResponse(json={"token": "d2", "signers": [{"token": "s2", "status": "new"}, {"token": "s3"}]}),
            ],
        )

        assert [(row["_documents_token"], row["token"]) for row in result.rows] == [
            ("d1", "s1"),
            ("d2", "s2"),
            ("d2", "s3"),
        ]
        assert result.urls[1].startswith(f"{ZAPSIGN_BASE_URL}/api/v1/docs/d1/")
        assert result.urls[2].startswith(f"{ZAPSIGN_BASE_URL}/api/v1/docs/d2/")
        # Composite key: signer tokens aren't documented as globally unique.
        assert result.response is not None
        assert result.response.primary_keys == ["_documents_token", "token"]
        assert result.response.partition_keys is None


class TestWebhookTableTransformer:
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


class TestCreateWebhook:
    def test_registers_all_document_events_with_generated_auth_header(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            result = create_webhook("token-123", "production", "https://webhooks.posthog.com/dwh/abc")

        assert result.success is True
        request = network.requests_log[0]
        assert request.origin + request.path == f"{ZAPSIGN_BASE_URL}/api/v1/user/company/webhook/"
        body = request.json()
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
    def test_reports_http_errors(self, _name: str, status_code: int, expected_error: str) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            result = create_webhook("token-123", "production", "https://webhooks.posthog.com/dwh/abc")

        assert result.success is False
        assert expected_error in cast("str", result.error)

    def test_reports_network_errors(self) -> None:
        with scripted_network(always(requests.ConnectionError("dns fail"))):
            result = create_webhook("token-123", "production", "https://webhooks.posthog.com/dwh/abc")

        assert result.success is False
        assert "Could not reach ZapSign" in cast("str", result.error)
