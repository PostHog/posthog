from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lemonsqueezy import (
    LemonSqueezySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.lemon_squeezy import (
    LemonSqueezyResumeConfig,
    LemonSqueezyUntrustedURLError,
    _assert_lemon_squeezy_origin,
    _flatten_json_api_item,
    _parse_datetime,
    _webhook_table_transformer,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    sync_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.settings import (
    ALL_WEBHOOK_EVENTS,
    BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.source import LemonSqueezySource


def _json_api_item(resource_id: str, created_at: str, **attributes: Any) -> dict[str, Any]:
    return {
        "type": "orders",
        "id": resource_id,
        "attributes": {"created_at": created_at, **attributes},
    }


def _page(items: list[dict[str, Any]], next_link: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "links": {"next": next_link} if next_link else {}})


def _driver() -> SourceDriver:
    return SourceDriver(LemonSqueezySource(), LemonSqueezySourceConfig(api_key="test-api-key"))


class TestParseDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            ("2024-05-01T10:00:00.000000Z", datetime(2024, 5, 1, 10, tzinfo=UTC)),
            ("2024-05-01T10:00:00+02:00", datetime(2024, 5, 1, 8, tzinfo=UTC)),
            (datetime(2024, 5, 1, 10), datetime(2024, 5, 1, 10, tzinfo=UTC)),
            (1714557600, datetime(2024, 5, 1, 10, tzinfo=UTC)),
            ("not-a-date", None),
        ],
    )
    def test_values(self, value, expected):
        assert _parse_datetime(value) == expected


class TestFlatten:
    def test_missing_attributes_still_yields_id(self):
        assert _flatten_json_api_item({"type": "orders", "id": "17"}) == {"id": "17"}


class TestValidateCredentials:
    def test_probes_users_me_with_json_api_headers(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("key") is True

        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.url == "https://api.lemonsqueezy.com/v1/users/me"
        assert request.headers["authorization"] == "Bearer key"
        assert request.headers["accept"] == "application/vnd.api+json"


class TestPagination:
    def test_follows_links_next_and_drops_original_params(self) -> None:
        next_url = f"{BASE_URL}/v1/stores?page%5Bnumber%5D=2"
        result = _driver().run(
            "stores",
            [
                _page(
                    [_json_api_item("1", "2024-05-02T00:00:00Z"), _json_api_item("2", "2024-05-01T00:00:00Z")],
                    next_url,
                ),
                _page([_json_api_item("3", "2024-04-30T00:00:00Z")]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert result.requests[0].path == "/v1/stores"
        assert result.requests[0].param("page[size]") == "100"
        # The next-page URL is self-contained; original params are dropped.
        assert result.requests[1].url == next_url
        assert result.requests[1].param("page[size]") is None
        # State is saved only while a next page exists.
        assert result.saved_states == [LemonSqueezyResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_state(self) -> None:
        resume_url = f"{BASE_URL}/v1/stores?page%5Bnumber%5D=5"
        result = _driver().run(
            "stores",
            [_page([_json_api_item("9", "2024-05-01T00:00:00Z")])],
            resume_state=LemonSqueezyResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["9"]
        assert result.requests[0].url == resume_url
        assert result.requests[0].param("page[size]") is None

    def test_incremental_stops_once_page_predates_watermark(self) -> None:
        result = _driver().run(
            "order_items",
            [
                # Page 1 straddles the watermark: keep paging.
                _page(
                    [_json_api_item("3", "2024-05-03T00:00:00Z"), _json_api_item("2", "2024-04-30T00:00:00Z")],
                    f"{BASE_URL}/v1/order-items?page%5Bnumber%5D=2",
                ),
                # Page 2 is entirely older than the watermark: stop despite a next link.
                _page(
                    [_json_api_item("1", "2024-04-29T00:00:00Z")],
                    f"{BASE_URL}/v1/order-items?page%5Bnumber%5D=3",
                ),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01T00:00:00Z",
        )

        assert result.raised is None
        assert len(result.requests) == 2
        # Boundary rows older than the watermark are re-yielded; merge on id dedupes them.
        assert [row["id"] for row in result.rows] == ["3", "2", "1"]


class TestWebhookTableTransformer:
    def test_flattens_and_keeps_latest_version_per_id(self):
        table = table_from_py_list(
            [
                {
                    "meta": {"event_name": "subscription_created"},
                    "data": {
                        "type": "subscriptions",
                        "id": "1",
                        "attributes": {"status": "on_trial", "updated_at": "2024-05-01T00:00:00Z"},
                    },
                },
                {
                    "meta": {"event_name": "subscription_updated"},
                    "data": {
                        "type": "subscriptions",
                        "id": "1",
                        "attributes": {"status": "active", "updated_at": "2024-05-02T00:00:00Z"},
                    },
                },
                {
                    "meta": {"event_name": "subscription_created"},
                    "data": {
                        "type": "subscriptions",
                        "id": "2",
                        "attributes": {"status": "active", "updated_at": "2024-05-01T00:00:00Z"},
                    },
                },
            ]
        )

        result = _webhook_table_transformer(table).to_pylist()

        by_id = {row["id"]: row for row in result}
        assert set(by_id) == {"1", "2"}
        assert by_id["1"]["status"] == "active"

    def test_missing_data_column_yields_empty_table(self):
        table = table_from_py_list([{"meta": {"event_name": "order_created"}}])
        assert _webhook_table_transformer(table).num_rows == 0


def _list_response(items: list[dict[str, Any]]) -> ScriptedResponse:
    return _page(items)


class TestWebhookManagement:
    def test_create_webhook_creates_one_per_store_with_shared_secret(self) -> None:
        with scripted_network(
            [
                _list_response(
                    [
                        {"type": "stores", "id": "1", "attributes": {}},
                        {"type": "stores", "id": "2", "attributes": {}},
                    ]
                ),
                ScriptedResponse(status=201),
                ScriptedResponse(status=201),
            ]
        ) as network:
            result = create_webhook("key", "https://us.posthog.com/webhooks/abc")

        assert result.success is True
        secret = result.extra_inputs["signing_secret"]
        assert 6 <= len(secret) <= 40

        assert [request.method for request in network.requests_log] == ["GET", "POST", "POST"]
        payloads = [request.json() for request in network.requests_log[1:]]
        assert {p["data"]["relationships"]["store"]["data"]["id"] for p in payloads} == {"1", "2"}
        for payload in payloads:
            attributes = payload["data"]["attributes"]
            assert attributes["url"] == "https://us.posthog.com/webhooks/abc"
            assert attributes["events"] == ALL_WEBHOOK_EVENTS
            # A single secret across stores — the hog function only stores one.
            assert attributes["secret"] == secret

    def test_create_webhook_fails_without_stores(self) -> None:
        with scripted_network([_list_response([])]) as network:
            result = create_webhook("key", "https://us.posthog.com/webhooks/abc")

        assert result.success is False
        assert "manually" in (result.error or "")
        assert [request.method for request in network.requests_log] == ["GET"]

    def test_create_webhook_succeeds_when_any_store_succeeds(self) -> None:
        with scripted_network(
            [
                _list_response(
                    [
                        {"type": "stores", "id": "1", "attributes": {}},
                        {"type": "stores", "id": "2", "attributes": {}},
                    ]
                ),
                ScriptedResponse(status=201),
                ScriptedResponse(status=422),
            ]
        ) as network:
            result = create_webhook("key", "https://us.posthog.com/webhooks/abc")

        assert result.success is True
        assert "signing_secret" in result.extra_inputs
        assert [request.method for request in network.requests_log] == ["GET", "POST", "POST"]

    def test_delete_webhook_removes_only_matching_urls(self) -> None:
        with scripted_network(
            [
                _list_response(
                    [
                        {"type": "webhooks", "id": "10", "attributes": {"url": "https://us.posthog.com/webhooks/abc"}},
                        {"type": "webhooks", "id": "11", "attributes": {"url": "https://elsewhere.example.com"}},
                    ]
                ),
                ScriptedResponse(status=204),
            ]
        ) as network:
            result = delete_webhook("key", "https://us.posthog.com/webhooks/abc")

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET", "DELETE"]
        assert network.requests_log[1].path == "/v1/webhooks/10"

    def test_get_external_webhook_info(self) -> None:
        with scripted_network(
            [
                _list_response(
                    [
                        {
                            "type": "webhooks",
                            "id": "10",
                            "attributes": {
                                "url": "https://us.posthog.com/webhooks/abc",
                                "events": ["order_created"],
                                "created_at": "2024-05-01T00:00:00Z",
                            },
                        },
                    ]
                )
            ]
        ):
            info = get_external_webhook_info("key", "https://us.posthog.com/webhooks/abc")

        assert info.exists is True
        assert info.enabled_events == ["order_created"]

    def test_get_external_webhook_info_not_found(self) -> None:
        with scripted_network([_list_response([])]):
            info = get_external_webhook_info("key", "https://us.posthog.com/webhooks/abc")

        assert info.exists is False

    def test_sync_webhook_events_merges_missing_events(self) -> None:
        with scripted_network(
            [
                _list_response(
                    [
                        {
                            "type": "webhooks",
                            "id": "10",
                            "attributes": {
                                "url": "https://us.posthog.com/webhooks/abc",
                                "events": ["order_created", "custom_extra_event"],
                            },
                        },
                    ]
                ),
                ScriptedResponse(),
            ]
        ) as network:
            result = sync_webhook_events(
                "key", "https://us.posthog.com/webhooks/abc", ["order_created", "order_refunded"]
            )

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET", "PATCH"]
        payload = network.requests_log[1].json()
        # Desired events are added; manually-added extras are preserved.
        assert payload["data"]["attributes"]["events"] == ["custom_extra_event", "order_created", "order_refunded"]

    def test_sync_webhook_events_skips_patch_when_already_subscribed(self) -> None:
        with scripted_network(
            [
                _list_response(
                    [
                        {
                            "type": "webhooks",
                            "id": "10",
                            "attributes": {"url": "https://us.posthog.com/webhooks/abc", "events": ["order_created"]},
                        },
                    ]
                )
            ]
        ) as network:
            result = sync_webhook_events("key", "https://us.posthog.com/webhooks/abc", ["order_created"])

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET"]


class TestCredentialLeakHardening:
    """Guards the SSRF / credential-exposure controls: pinning credentialed requests to the
    Lemon Squeezy origin and keeping secret-bearing responses out of HTTP sample capture."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com/v1/orders",  # off-host
            "http://api.lemonsqueezy.com/v1/orders",  # scheme downgrade to http
            "https://api.lemonsqueezy.com:8443/v1/orders",  # non-default port
            "https://api.lemonsqueezy.com.evil.com/v1/orders",  # look-alike host
            "https://api.lemonsqueezy.com/internal/orders",  # off the /v1/ prefix
        ],
    )
    def test_iterate_list_refuses_off_origin_next_url(self, url):
        with pytest.raises(LemonSqueezyUntrustedURLError):
            _assert_lemon_squeezy_origin(url)

    def test_iterate_list_allows_api_origin(self):
        # A legitimate next link must not be rejected.
        _assert_lemon_squeezy_origin(f"{BASE_URL}/v1/webhooks?page%5Bnumber%5D=2")
