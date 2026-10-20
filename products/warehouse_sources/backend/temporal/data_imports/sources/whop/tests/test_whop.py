from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whop import WhopSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.settings import (
    ALL_WEBHOOK_EVENTS,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    WHOP_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.source import WhopSource
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.whop import (
    WhopCursorPaginator,
    WhopResumeConfig,
    _list_params,
    _parse_datetime,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    sync_webhook_events,
    validate_credentials,
    webhook_table_transformer,
)

COMPANY_ID = "biz_test"

LEGACY = "2025-01-01"
LATEST = "2026-10-13-1"

SYNC_ENDPOINT = "payments"


def _page(items: list[dict[str, Any]], end_cursor: str | None, has_next_page: bool) -> ScriptedResponse:
    body = {
        "data": items,
        "page_info": {
            "end_cursor": end_cursor,
            "start_cursor": None,
            "has_next_page": has_next_page,
            "has_previous_page": False,
        },
        "total_count": len(items),
    }
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(WhopSource(), WhopSourceConfig(api_key="test-api-key", company_id=COMPANY_ID))


class TestParseDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            ("2024-05-01T10:00:00.401Z", datetime(2024, 5, 1, 10, 0, 0, 401000, tzinfo=UTC)),
            ("2024-05-01T10:00:00+02:00", datetime(2024, 5, 1, 8, tzinfo=UTC)),
            (datetime(2024, 5, 1, 10), datetime(2024, 5, 1, 10, tzinfo=UTC)),
            (1714557600, datetime(2024, 5, 1, 10, tzinfo=UTC)),
            ("not-a-date", None),
        ],
    )
    def test_values(self, value, expected):
        assert _parse_datetime(value) == expected


class TestListParams:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @pytest.mark.parametrize(
        "api_version, filter_param, other_param",
        [(LEGACY, "company_id", "account_id"), (LATEST, "account_id", "company_id")],
    )
    def test_company_and_page_size_always_sent(self, endpoint, api_version, filter_param, other_param):
        params = _list_params(endpoint, COMPANY_ID, None, api_version)
        assert params[filter_param] == COMPANY_ID
        assert other_param not in params
        assert params["first"] == PAGE_SIZE

    @pytest.mark.parametrize(
        "endpoint",
        [name for name, config in WHOP_ENDPOINTS.items() if not config.supports_created_after],
    )
    def test_endpoints_without_the_filter_never_send_created_after(self, endpoint):
        # These resources carry no trackable `created_at`; sending the filter would silently drop
        # rows the pipeline would then never backfill.
        assert "created_after" not in _list_params(endpoint, COMPANY_ID, datetime(2024, 5, 1, tzinfo=UTC), LEGACY)


class TestApiVersion:
    @pytest.mark.parametrize(
        "pinned, sent_version, filter_param, endpoint, path",
        [
            (LEGACY, LEGACY, "company_id", "entries", "/api/v1/entries"),
            (LATEST, LATEST, "account_id", "entries", "/api/v1/waitlist_entries"),
            # A row created by a pod still on the unversioned code during the deploy.
            ("v1", LEGACY, "company_id", "products", "/api/v1/products"),
            (None, LATEST, "account_id", "products", "/api/v1/products"),
        ],
    )
    def test_sync_sends_the_pinned_version(self, pinned, sent_version, filter_param, endpoint, path):
        result = _driver().run(endpoint, [_page([], end_cursor=None, has_next_page=False)], api_version=pinned)

        request = result.requests[0]
        assert request.headers["api-version-date"] == sent_version
        assert request.path == path
        assert request.param(filter_param) == COMPANY_ID


class TestPagination:
    def test_follows_end_cursor_and_saves_resume_state(self):
        result = _driver().run(
            SYNC_ENDPOINT,
            [
                _page([{"id": "pay_1"}], end_cursor="cursor-1", has_next_page=True),
                _page([{"id": "pay_2"}], end_cursor="cursor-2", has_next_page=False),
            ],
        )

        assert [row["id"] for row in result.rows] == ["pay_1", "pay_2"]
        assert result.params("after") == [None, "cursor-1"]
        # State is persisted only while a next page remains, after the page was yielded.
        assert result.saved_states == [WhopResumeConfig(cursor="cursor-1")]

    def test_resumes_from_saved_cursor(self):
        result = _driver().run(
            SYNC_ENDPOINT,
            [_page([{"id": "pay_9"}], end_cursor="cursor-9", has_next_page=False)],
            resume_state=WhopResumeConfig(cursor="cursor-8"),
        )

        assert [row["id"] for row in result.rows] == ["pay_9"]
        assert result.params("after") == ["cursor-8"]

    def test_paginator_stops_on_unparseable_body(self):
        # Nothing to page with, so stopping beats re-requesting the same cursor forever.
        response = Response()
        response.status_code = 200
        response._content = b"not json"

        paginator = WhopCursorPaginator()
        paginator.update_state(response, [])

        assert paginator.has_next_page is False


class TestSourceResponseMetadata:
    def test_framework_incremental_injection_is_not_used(self):
        # `created_after` is baked into the request params; letting the framework also inject the
        # watermark would add a second, wrongly-named filter param.
        result = _driver().run(
            SYNC_ENDPOINT,
            [_page([], end_cursor=None, has_next_page=False)],
            incremental_field="created_at",
            db_incremental_field_last_value="2024-05-01T10:00:00Z",
        )

        assert result.requests[0].param("created_after") == "2024-05-01T10:00:00.000Z"
        assert set(result.requests[0].query) == {"first", "account_id", "created_after", "order", "direction"}


class TestWebhookTableTransformer:
    def test_skips_rows_without_a_resource_id(self):
        table = table_from_py_list(
            [
                {"id": "msg_1", "timestamp": "2024-05-01T00:00:00Z", "data": {"status": "paid"}},
                {"id": "msg_2", "timestamp": "2024-05-01T00:00:00Z", "data": {"id": "pay_1"}},
            ]
        )

        assert webhook_table_transformer(table).to_pylist() == [{"id": "pay_1"}]

    def test_empty_when_deliveries_carry_no_data_column(self):
        table = table_from_py_list([{"id": "msg_1", "type": "payment.succeeded"}])

        assert webhook_table_transformer(table).num_rows == 0


class TestValidateCredentials:
    @pytest.mark.parametrize("api_version, resource", [(LEGACY, "companies"), (LATEST, "accounts")])
    def test_probes_the_connected_company_with_a_bearer_token(self, api_version, resource):
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("key", COMPANY_ID, api_version)

        request = network.requests_log[0]
        assert request.url == f"{BASE_URL}/{resource}/{COMPANY_ID}"
        assert request.headers["authorization"] == "Bearer key"
        assert request.headers["api-version-date"] == api_version

    def test_transport_failure_never_raises(self):
        with scripted_network(always(ConnectionError("boom"))):
            assert validate_credentials("key", COMPANY_ID, LEGACY) == (False, None)


WEBHOOK_URL = "https://ph.example/webhook"


class TestCreateWebhook:
    @pytest.mark.parametrize(
        "api_version, version_fields",
        [
            # An unpinned v1 webhook delivers the "2025-01-01" shape the legacy pulls return.
            (LEGACY, {"api_version": "v1"}),
            # Later versions reject `api_version` with a 400, and the pin keeps deliveries in the
            # shape the latest pulls return.
            (LATEST, {"api_version_date": LATEST}),
        ],
    )
    def test_returns_the_generated_signing_secret(self, api_version, version_fields):
        with scripted_network(
            [ScriptedResponse(status=201, json={"id": "hook_1", "webhook_secret": "whsec_abc"})]
        ) as network:
            result = create_webhook("key", COMPANY_ID, WEBHOOK_URL, api_version)

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "whsec_abc"}
        payload = network.requests_log[0].json()
        assert payload == {
            "url": WEBHOOK_URL,
            "events": ALL_WEBHOOK_EVENTS,
            "resource_id": COMPANY_ID,
            "enabled": True,
            **version_fields,
        }

    @pytest.mark.parametrize("status_code", [401, 403, 422, 500])
    def test_non_success_falls_back_to_manual_setup(self, status_code):
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            result = create_webhook("key", COMPANY_ID, WEBHOOK_URL, LEGACY)

        assert result.success is False
        assert result.error is not None
        # Vendor status codes belong in error tracking, not in what the customer reads.
        assert str(status_code) not in result.error

    def test_missing_secret_is_a_failure(self):
        # Without a secret the hog function cannot verify deliveries, so reporting success would
        # silently leave the webhook rejecting every payload.
        with scripted_network([ScriptedResponse(status=201, json={"id": "hook_1"})]):
            result = create_webhook("key", COMPANY_ID, WEBHOOK_URL, LEGACY)

        assert result.success is False

    def test_transport_failure_is_reported_not_raised(self):
        with scripted_network(always(ConnectionError("boom"))):
            assert create_webhook("key", COMPANY_ID, WEBHOOK_URL, LEGACY).success is False


def _webhook_list_page(items: list[dict[str, Any]], end_cursor: str | None, has_next_page: bool) -> ScriptedResponse:
    return ScriptedResponse(
        json={"data": items, "page_info": {"end_cursor": end_cursor, "has_next_page": has_next_page}}
    )


def _webhook_api(
    webhooks: list[dict[str, Any]], on_write: Callable[[RecordedRequest], ScriptedResponse] | None = None
) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.method == "GET":
            return _webhook_list_page(webhooks, None, False)
        assert on_write is not None
        return on_write(request)

    return respond


def _writes(requests_log: list[RecordedRequest], method: str) -> list[RecordedRequest]:
    return [request for request in requests_log if request.method == method]


class TestWebhookManagement:
    @pytest.mark.parametrize("api_version, filter_param", [(LEGACY, "company_id"), (LATEST, "account_id")])
    def test_lookup_pages_through_every_webhook(self, api_version, filter_param):
        with scripted_network(
            [
                _webhook_list_page([{"id": "hook_1", "url": "https://other.example"}], "cursor-1", True),
                _webhook_list_page(
                    [{"id": "hook_2", "url": WEBHOOK_URL, "events": ["payment.succeeded"], "enabled": True}],
                    None,
                    False,
                ),
            ]
        ) as network:
            info = get_external_webhook_info("key", COMPANY_ID, WEBHOOK_URL, api_version)

        assert info.exists is True
        assert info.enabled_events == ["payment.succeeded"]
        assert info.status == "enabled"
        assert network.requests_log[1].param("after") == "cursor-1"
        assert network.requests_log[0].param(filter_param) == COMPANY_ID

    def test_lookup_reports_absence(self):
        with scripted_network([_webhook_list_page([], None, False)]):
            assert get_external_webhook_info("key", COMPANY_ID, WEBHOOK_URL, LEGACY).exists is False

    def test_sync_merges_missing_events_and_keeps_existing_ones(self):
        webhooks = [{"id": "hook_1", "url": WEBHOOK_URL, "events": ["payment.created", "custom.event"]}]

        with scripted_network(_webhook_api(webhooks, always(ScriptedResponse(json={})))) as network:
            result = sync_webhook_events("key", COMPANY_ID, WEBHOOK_URL, ["payment.succeeded"], LEGACY)

        assert result.success is True
        assert _writes(network.requests_log, "PATCH")[0].json() == {
            "events": ["custom.event", "payment.created", "payment.succeeded"]
        }

    def test_sync_skips_the_write_when_events_already_match(self):
        webhooks = [{"id": "hook_1", "url": WEBHOOK_URL, "events": ["payment.succeeded"]}]

        with scripted_network(_webhook_api(webhooks)) as network:
            assert sync_webhook_events("key", COMPANY_ID, WEBHOOK_URL, ["payment.succeeded"], LEGACY).success

        assert _writes(network.requests_log, "PATCH") == []

    def test_delete_removes_only_matching_webhooks(self):
        webhooks = [
            {"id": "hook_1", "url": "https://other.example"},
            {"id": "hook_2", "url": WEBHOOK_URL},
        ]

        with scripted_network(_webhook_api(webhooks, always(ScriptedResponse(status=204)))) as network:
            result = delete_webhook("key", COMPANY_ID, WEBHOOK_URL, LEGACY)

        assert result.success is True
        deletes = _writes(network.requests_log, "DELETE")
        assert [request.path.rsplit("/", 1)[-1] for request in deletes] == ["hook_2"]

    def test_delete_surfaces_a_rejected_removal(self):
        webhooks = [{"id": "hook_2", "url": WEBHOOK_URL}]

        with scripted_network(_webhook_api(webhooks, always(ScriptedResponse(status=403)))):
            assert delete_webhook("key", COMPANY_ID, WEBHOOK_URL, LEGACY).success is False
