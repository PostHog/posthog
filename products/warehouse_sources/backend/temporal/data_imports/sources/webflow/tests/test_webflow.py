from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.webflow import (
    WebflowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import (
    ALL_WEBHOOK_EVENTS,
    WEBFLOW_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.source import WebflowSource
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow import (
    WebflowResumeConfig,
    _extract_items,
    _resolve_collection_id,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    validate_credentials,
    webflow_source,
    webhook_table_transformer,
)

# The sync transport builds its session via make_tracked_session inside the shared rest_client.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _make_manager(resume_state: WebflowResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _driver() -> SourceDriver:
    source = WebflowSource()
    config: WebflowSourceConfig = source.parse_config({"api_token": "token", "site_id": "site-1"})
    return SourceDriver(source, config)


def _page(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


class TestExtractItems:
    @parameterized.expand(
        [
            ("configured_key", {"items": [{"id": 1}]}, "items", [{"id": 1}]),
            ("named_envelope", {"sites": [{"id": 1}]}, "sites", [{"id": 1}]),
            ("bare_list", [{"id": 1}], "items", [{"id": 1}]),
            ("missing_key_fallback", {"weird": [{"id": 7}], "pagination": {}}, "items", [{"id": 7}]),
            ("pagination_skipped", {"pagination": [1, 2], "orders": [{"id": 9}]}, "orders", [{"id": 9}]),
            ("nothing", {"pagination": {}}, "items", []),
            ("not_a_dict", 5, "items", []),
        ]
    )
    def test_extract_items(self, _name: str, data: Any, data_key: str, expected: list[dict[str, Any]]) -> None:
        assert _extract_items(data, data_key) == expected


class TestGetRows:
    def test_fresh_run_paginates_until_total_and_saves_after_each_page(self) -> None:
        # Full pages until the grand total (pagination.total) is reached; offset advances by page size.
        page1 = [{"id": f"a{i}"} for i in range(100)]
        page2 = [{"id": f"b{i}"} for i in range(100)]
        page3 = [{"id": f"c{i}"} for i in range(50)]
        result = _driver().run(
            "pages",
            [
                _page({"pages": page1, "pagination": {"total": 250, "offset": 0}}),
                _page({"pages": page2, "pagination": {"total": 250, "offset": 100}}),
                _page({"pages": page3, "pagination": {"total": 250, "offset": 200}}),
            ],
        )

        assert len(result.rows) == 250
        assert result.params("offset") == ["0", "100", "200"]
        assert result.params("limit") == ["100", "100", "100"]
        # A checkpoint (pointing at the next page) is saved after each non-terminal page; the
        # final page terminates via total and saves nothing.
        assert result.saved_states == [WebflowResumeConfig(offset=100), WebflowResumeConfig(offset=200)]

    def test_resume_starts_from_saved_offset(self) -> None:
        result = _driver().run(
            "pages",
            [_page({"pages": [{"id": "c"}], "pagination": {"total": 250, "offset": 200}})],
            resume_state=WebflowResumeConfig(offset=200),
        )

        assert result.rows == [{"id": "c"}]
        assert result.params("offset")[0] == "200"

    def test_single_object_endpoint_wraps_one_row_and_fetches_once(self) -> None:
        # /sites/{site_id} returns a single site object, not a list envelope.
        result = _driver().run("sites", [_page({"id": "s1", "displayName": "My site"})])

        assert result.rows == [{"id": "s1", "displayName": "My site"}]
        assert result.urls == ["https://api.webflow.com/v2/sites/site-1"]
        # Not paginated: no offset/limit params are injected.
        assert result.params("offset") == [None]
        assert result.saved_states == []

    def test_products_endpoint_flattens_nested_product(self) -> None:
        result = _driver().run(
            "products",
            [_page({"items": [{"product": {"id": "p1", "createdOn": "2026-01-01"}, "skus": [{"id": "s1"}]}]})],
        )

        assert result.rows == [{"id": "p1", "createdOn": "2026-01-01", "skus": [{"id": "s1"}]}]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("pages", [_page({"pages": [{"id": "a"}]})])

        assert result.params("offset") == ["0"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("bad_token", 401, None, False),
            ("missing_scope_at_create", 403, None, True),
            ("missing_scope_for_schema", 403, "products", False),
            ("invalid_site_id", 400, None, False),
            ("site_not_found", 404, None, False),
            ("server_error", 500, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, schema_name: str | None, expected_ok: bool) -> None:
        with scripted_network(always(_page({"message": "nope"}, status_code))):
            ok, _error = validate_credentials("token", "site-1", schema_name)
        assert ok is expected_ok

    def test_invalid_site_id_400_does_not_leak_raw_envelope(self) -> None:
        # A malformed Site ID gets a 400 with Webflow's raw "Validation Error: ..." envelope, which
        # must not surface to the user.
        with scripted_network(always(_page({"message": "Validation Error: Provided IDs are invalid: Site ID"}, 400))):
            ok, error = validate_credentials("token", "site-1")
        assert ok is False
        assert "Site ID isn't valid" in (error or "")
        assert "Validation Error" not in (error or "")


class TestResolveCollectionId:
    def test_resolves_by_slug(self) -> None:
        with scripted_network(
            [_page({"collections": [{"id": "c1", "slug": "blog"}, {"id": "c2", "slug": "authors"}]})]
        ):
            assert _resolve_collection_id("token", "site-1", "collection_authors") == "c2"

    def test_raises_when_collection_missing(self) -> None:
        with scripted_network([_page({"collections": [{"id": "c1", "slug": "blog"}]})]):
            with pytest.raises(ValueError):
                _resolve_collection_id("token", "site-1", "collection_missing")


class TestWebflowSource:
    @parameterized.expand(
        [
            ("pages", "pages", ["id"]),
            ("products", "products", ["id"]),
            ("orders", "orders", ["orderId"]),
        ]
    )
    def test_source_response_primary_keys(self, _name: str, schema_name: str, expected_pks: list[str]) -> None:
        result = _driver().run(schema_name, always(_page({})))

        assert result.response is not None
        assert result.response.name == schema_name
        assert result.response.primary_keys == expected_pks
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == [WEBFLOW_ENDPOINTS[schema_name].partition_key]


WEBHOOK_URL = "https://webhooks.example/dwh/1"


def _webhook_list_response(webhooks: list[dict[str, Any]]) -> ScriptedResponse:
    return _page({"webhooks": webhooks, "pagination": {"limit": 100, "offset": 0, "total": len(webhooks)}})


def _webhook_api(
    webhooks: list[dict[str, Any]],
    on_post: Callable[[RecordedRequest], ScriptedResponse] | None = None,
    on_delete: Callable[[RecordedRequest], ScriptedResponse] | None = None,
) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.method == "GET":
            return _webhook_list_response(webhooks)
        handler = on_post if request.method == "POST" else on_delete
        assert handler is not None
        return handler(request)

    return respond


def _posted_triggers(requests_log: list[RecordedRequest]) -> list[str]:
    return [request.json()["triggerType"] for request in requests_log if request.method == "POST"]


class TestCreateWebhook:
    def test_registers_one_webhook_per_trigger_and_keeps_every_secret(self) -> None:
        # Webflow's create endpoint takes a single triggerType and issues a separate secret per
        # registration, so losing any of them leaves that trigger's deliveries unverifiable.
        secrets = {"ecomm_new_order": "s1", "ecomm_order_changed": "s2"}

        def on_post(request: RecordedRequest) -> ScriptedResponse:
            trigger = request.json()["triggerType"]
            return _page({"id": f"w-{trigger}", "triggerType": trigger, "secretKey": secrets[trigger]}, 201)

        with scripted_network(_webhook_api([], on_post)) as network:
            result = create_webhook("token", "site-1", WEBHOOK_URL)

        assert result.success is True
        assert result.extra_inputs == {"signing_secrets": ["s1", "s2"], "signing_secrets_complete": True}
        assert result.pending_inputs == []
        assert _posted_triggers(network.requests_log) == list(ALL_WEBHOOK_EVENTS)
        assert {request.json()["url"] for request in network.requests_log if request.method == "POST"} == {WEBHOOK_URL}

    def test_skips_triggers_already_registered_for_our_url(self) -> None:
        # Webflow caps registrations per trigger type per site, and a duplicate would keep
        # delivering after we delete "the" webhook.
        existing = [{"id": "w1", "triggerType": "ecomm_new_order", "url": WEBHOOK_URL}]
        on_post = always(_page({"id": "w2", "triggerType": "ecomm_order_changed", "secretKey": "s2"}, 201))

        with scripted_network(_webhook_api(existing, on_post)) as network:
            result = create_webhook("token", "site-1", WEBHOOK_URL)

        assert _posted_triggers(network.requests_log) == ["ecomm_order_changed"]
        assert result.success is True
        # One trigger's secret was issued before we asked, so it can't be recovered.
        assert result.pending_inputs == ["signing_secret"]
        # A non-empty secret list does not mean setup is done. Without this flag the webhook tab
        # reads the list as complete and hides the warning, while the triggers whose secret we
        # never saw keep failing the signature check.
        assert result.extra_inputs == {"signing_secrets": ["s2"], "signing_secrets_complete": False}

    def test_registration_without_a_secret_asks_the_user_for_one(self) -> None:
        # Site tokens predating Webflow's per-webhook secrets return no secretKey; silently
        # succeeding would leave every delivery failing the signature check.
        with scripted_network(_webhook_api([], always(_page({"id": "w1"}, 201)))):
            result = create_webhook("token", "site-1", WEBHOOK_URL)

        assert result.success is True
        assert result.extra_inputs == {}
        assert result.pending_inputs == ["signing_secret"]

    @parameterized.expand([("forbidden", 403), ("bad_request", 400)])
    def test_reports_failure_when_no_registration_was_created(self, _name: str, status_code: int) -> None:
        with scripted_network(_webhook_api([], always(_page({"message": "nope"}, status_code)))):
            result = create_webhook("token", "site-1", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None
        assert "sites:write" in result.error

    def test_network_failure_is_reported_not_raised(self) -> None:
        with scripted_network(always(requests.exceptions.ConnectTimeout("boom"))):
            result = create_webhook("token", "site-1", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "boom" in result.error


class TestDeleteWebhook:
    def test_deletes_every_registration_pointing_at_our_url_and_leaves_others(self) -> None:
        webhooks = [
            {"id": "w1", "triggerType": "ecomm_new_order", "url": WEBHOOK_URL},
            {"id": "w2", "triggerType": "ecomm_order_changed", "url": WEBHOOK_URL},
            {"id": "other", "triggerType": "form_submission", "url": "https://someone-else.example"},
        ]

        # A registration removed in Webflow between listing and deleting is already the
        # outcome we wanted, so a 404 must not fail the teardown.
        def on_delete(request: RecordedRequest) -> ScriptedResponse:
            return _page({}, 404 if request.path.endswith("/w2") else 204)

        with scripted_network(_webhook_api(webhooks, on_delete=on_delete)) as network:
            result = delete_webhook("token", "site-1", WEBHOOK_URL)

        assert result.success is True
        deleted_ids = [
            request.path.rsplit("/", 1)[-1] for request in network.requests_log if request.method == "DELETE"
        ]
        assert deleted_ids == ["w1", "w2"]

    def test_reports_a_registration_webflow_refused_to_delete(self) -> None:
        webhooks = [{"id": "w1", "triggerType": "ecomm_new_order", "url": WEBHOOK_URL}]

        with scripted_network(_webhook_api(webhooks, on_delete=always(_page({}, 403)))):
            result = delete_webhook("token", "site-1", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "w1" in result.error


class TestGetExternalWebhookInfo:
    def test_reports_the_triggers_currently_registered(self) -> None:
        webhooks = [
            {
                "id": "w1",
                "triggerType": "ecomm_new_order",
                "url": WEBHOOK_URL,
                "createdOn": "2026-01-02T00:00:00Z",
            },
            {
                "id": "w2",
                "triggerType": "ecomm_order_changed",
                "url": WEBHOOK_URL,
                "createdOn": "2026-01-01T00:00:00Z",
            },
        ]

        with scripted_network([_webhook_list_response(webhooks)]):
            info = get_external_webhook_info("token", "site-1", WEBHOOK_URL)

        assert info.exists is True
        # The set drives the "missing events" hint in the UI, so a partial registration has to
        # report only what is really there.
        assert info.enabled_events == ["ecomm_new_order", "ecomm_order_changed"]
        assert info.created_at == "2026-01-01T00:00:00Z"

    def test_reports_absence_when_only_other_webhooks_exist(self) -> None:
        other = [{"id": "w1", "triggerType": "form_submission", "url": "https://someone-else.example"}]

        with scripted_network([_webhook_list_response(other)]):
            info = get_external_webhook_info("token", "site-1", WEBHOOK_URL)

        assert info.exists is False

    def test_lookup_failure_is_reported_not_raised(self) -> None:
        with scripted_network([_page({"message": "nope"}, 401)]):
            info = get_external_webhook_info("token", "site-1", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is not None


class TestWebhookTableTransformer:
    def _table(self, rows: list[dict[str, Any]]) -> Any:
        return table_from_py_list(rows)

    def test_rows_without_an_order_id_are_dropped(self) -> None:
        # A row with no primary key can't be merged; keeping it would fail the whole batch.
        table = self._table(
            [
                {"triggerType": "ecomm_new_order", "webflowTimestamp": "1700000000000", "payload": {"status": "x"}},
                {
                    "triggerType": "ecomm_new_order",
                    "webflowTimestamp": "1700000000000",
                    "payload": {"orderId": "abc123", "status": "unfulfilled"},
                },
            ]
        )

        assert webhook_table_transformer(table).to_pylist() == [{"orderId": "abc123", "status": "unfulfilled"}]

    def test_table_without_a_payload_column_yields_no_rows(self) -> None:
        assert webhook_table_transformer(self._table([{"triggerType": "site_publish"}])).num_rows == 0


class TestWebhookBackedSource:
    def test_orders_reads_from_the_webhook_manager_once_webhooks_are_live(self) -> None:
        manager = _make_manager()
        webhook_manager = MagicMock(spec=WebhookSourceManager)
        webhook_manager.webhook_enabled = AsyncMock(return_value=True)
        webhook_manager.get_items.return_value = "webhook-items"

        with patch(CLIENT_SESSION_PATCH) as MockSession:
            MockSession.return_value.send.side_effect = AssertionError("the pull API must not be hit")
            response = webflow_source(
                "token",
                "site-1",
                "orders",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                webhook_source_manager=webhook_manager,
            )
            assert response.items() == "webhook-items"

        webhook_manager.get_items.assert_called_once_with(table_transformer=webhook_table_transformer)
        # The polled table's identity must not change when rows arrive by webhook, or pushed
        # rows land in a different Delta table than the backfill.
        assert response.primary_keys == ["orderId"]
        assert response.partition_keys == ["acceptedOn"]

    @parameterized.expand([("pages",), ("collection_blog",)])
    def test_schema_without_webhook_support_never_consults_the_webhook_manager(self, schema_name: str) -> None:
        # Only `orders` has a Webflow trigger whose payload matches the polled table, so any
        # other schema must keep polling even when a webhook is registered on the source.
        webhook_manager = MagicMock(spec=WebhookSourceManager)
        webhook_manager.webhook_enabled = AsyncMock(return_value=True)

        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/collections"):
                return _page({"collections": [{"id": "c1", "slug": "blog"}]})
            return _page({"pages": [{"id": "p1"}], "items": [{"id": "p1"}]})

        with patch.object(WebflowSource, "get_webhook_source_manager", return_value=webhook_manager):
            result = _driver().run(schema_name, script)

        assert result.raised is None
        assert result.rows == [{"id": "p1"}]
        webhook_manager.webhook_enabled.assert_not_called()
        webhook_manager.get_items.assert_not_called()
