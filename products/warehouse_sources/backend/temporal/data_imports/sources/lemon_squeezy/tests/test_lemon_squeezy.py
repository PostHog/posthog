import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import TrackedHTTPAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.lemon_squeezy import (
    LemonSqueezyPaginator,
    LemonSqueezyResumeConfig,
    LemonSqueezyUntrustedURLError,
    _assert_lemon_squeezy_origin,
    _flatten_json_api_item,
    _make_session,
    _parse_datetime,
    _webhook_table_transformer,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    lemon_squeezy_source,
    sync_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.settings import (
    ALL_WEBHOOK_EVENTS,
    BASE_URL,
    INCREMENTAL_ENDPOINTS,
    LEMON_SQUEEZY_ENDPOINTS,
)

# The source builds its own tracked session (capture-disabled, host-pinned) for the sync client,
# validate_credentials, and the webhook management helpers.
LEMON_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.lemon_squeezy.make_tracked_session"
)


def _json_api_item(resource_id: str, created_at: str, **attributes: Any) -> dict[str, Any]:
    return {
        "type": "orders",
        "id": resource_id,
        "attributes": {"created_at": created_at, **attributes},
    }


def _response(items: list[dict[str, Any]], next_link: str | None) -> Response:
    body = {"data": items, "links": {"next": next_link} if next_link else {}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LemonSqueezyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request AT PREPARE TIME (params/url mutate across pages)."""
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "headers": request.headers or {}})
        # The prepared URL must be a real string: the client host-pins every request URL, so a
        # MagicMock here would blow up `urlsplit` in the allowed-host check.
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return lemon_squeezy_source(
        "test-api-key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
    def test_hoists_attributes_and_keeps_id(self):
        row = _flatten_json_api_item(
            {
                "type": "orders",
                "id": "17",
                "attributes": {"total": 999, "created_at": "2024-05-01T10:00:00Z"},
                "relationships": {"store": {}},
                "links": {"self": "https://api.lemonsqueezy.com/v1/orders/17"},
            }
        )
        assert row == {"id": "17", "total": 999, "created_at": "2024-05-01T10:00:00Z"}

    def test_missing_attributes_still_yields_id(self):
        assert _flatten_json_api_item({"type": "orders", "id": "17"}) == {"id": "17"}


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(LEMON_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key") is expected

    @mock.patch(LEMON_SESSION_PATCH)
    def test_probes_users_me_with_json_api_headers(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.lemonsqueezy.com/v1/users/me"
        assert call.kwargs["headers"]["Authorization"] == "Bearer key"
        assert call.kwargs["headers"]["Accept"] == "application/vnd.api+json"

    @mock.patch(LEMON_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False


class TestPagination:
    @mock.patch(LEMON_SESSION_PATCH)
    def test_follows_links_next_and_drops_original_params(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                _response(
                    [_json_api_item("1", "2024-05-02T00:00:00Z"), _json_api_item("2", "2024-05-01T00:00:00Z")],
                    "https://api.lemonsqueezy.com/v1/orders?page%5Bnumber%5D=2",
                ),
                _response([_json_api_item("3", "2024-04-30T00:00:00Z")], None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("orders", manager))

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        assert requests_seen[0]["url"] == "https://api.lemonsqueezy.com/v1/orders"
        assert requests_seen[0]["params"] == {"page[size]": 100}
        # The next-page URL is self-contained; original params are dropped.
        assert requests_seen[1]["url"] == "https://api.lemonsqueezy.com/v1/orders?page%5Bnumber%5D=2"
        assert requests_seen[1]["params"] == {}
        # State is saved only while a next page exists.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == LemonSqueezyResumeConfig(
            next_url="https://api.lemonsqueezy.com/v1/orders?page%5Bnumber%5D=2"
        )

    @mock.patch(LEMON_SESSION_PATCH)
    def test_rows_are_flattened(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([_json_api_item("1", "2024-05-02T00:00:00Z", total=999)], None)])

        rows = _rows(_source("orders", _make_manager()))

        assert rows == [{"id": "1", "created_at": "2024-05-02T00:00:00Z", "total": 999}]

    @mock.patch(LEMON_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response([_json_api_item("9", "2024-05-01T00:00:00Z")], None)])

        resume_url = "https://api.lemonsqueezy.com/v1/orders?page%5Bnumber%5D=5"
        rows = _rows(_source("orders", _make_manager(LemonSqueezyResumeConfig(next_url=resume_url))))

        assert [row["id"] for row in rows] == ["9"]
        assert requests_seen[0]["url"] == resume_url
        assert requests_seen[0]["params"] == {}

    @mock.patch(LEMON_SESSION_PATCH)
    def test_incremental_stops_once_page_predates_watermark(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                # Page 1 straddles the watermark: keep paging.
                _response(
                    [_json_api_item("3", "2024-05-03T00:00:00Z"), _json_api_item("2", "2024-04-30T00:00:00Z")],
                    "https://api.lemonsqueezy.com/v1/orders?page%5Bnumber%5D=2",
                ),
                # Page 2 is entirely older than the watermark: stop despite a next link.
                _response(
                    [_json_api_item("1", "2024-04-29T00:00:00Z")],
                    "https://api.lemonsqueezy.com/v1/orders?page%5Bnumber%5D=3",
                ),
            ],
        )

        manager = _make_manager()
        rows = _rows(
            _source(
                "orders",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-05-01T00:00:00Z",
            )
        )

        assert len(requests_seen) == 2
        # Boundary rows older than the watermark are re-yielded; merge on id dedupes them.
        assert [row["id"] for row in rows] == ["3", "2", "1"]

    @mock.patch(LEMON_SESSION_PATCH)
    def test_full_refresh_walks_past_old_pages(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                _response(
                    [_json_api_item("2", "2024-04-30T00:00:00Z")],
                    "https://api.lemonsqueezy.com/v1/orders?page%5Bnumber%5D=2",
                ),
                _response([_json_api_item("1", "2024-04-29T00:00:00Z")], None),
            ],
        )

        rows = _rows(_source("orders", _make_manager()))

        assert len(requests_seen) == 2
        assert [row["id"] for row in rows] == ["2", "1"]

    def test_paginator_keeps_paging_when_created_at_unparseable(self):
        # An upstream format change must degrade to a full walk, not silently stop the sync.
        paginator = LemonSqueezyPaginator(watermark=datetime(2024, 5, 1, tzinfo=UTC))
        response = _response([_json_api_item("1", "not-a-date")], "https://api.lemonsqueezy.com/v1/orders?page=2")

        paginator.update_state(response, response.json()["data"])

        assert paginator.has_next_page is True


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(LEMON_SQUEEZY_ENDPOINTS.keys()))
    @mock.patch(LEMON_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Lists arrive newest-first, so the watermark must only finalize after a full sync.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, expected_disposition",
        [
            ("orders", True, {"disposition": "merge", "strategy": "upsert"}),
            ("orders", False, "replace"),
            ("stores", False, "replace"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.lemon_squeezy.rest_api_resource"
    )
    def test_write_disposition_follows_incremental_mode(
        self, mock_rest_api_resource, endpoint, should_use_incremental_field, expected_disposition
    ):
        _source(endpoint, _make_manager(), should_use_incremental_field=should_use_incremental_field)

        config = mock_rest_api_resource.call_args.args[0]
        assert config["resources"][0]["write_disposition"] == expected_disposition

    def test_incremental_endpoints_use_created_at(self):
        for endpoint in INCREMENTAL_ENDPOINTS:
            fields = LEMON_SQUEEZY_ENDPOINTS[endpoint].incremental_fields
            assert [f["field"] for f in fields] == ["created_at"]


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

    def test_out_of_order_batch_keeps_newest(self):
        table = table_from_py_list(
            [
                {
                    "data": {
                        "type": "orders",
                        "id": "1",
                        "attributes": {"status": "refunded", "updated_at": "2024-05-02T00:00:00Z"},
                    }
                },
                {
                    "data": {
                        "type": "orders",
                        "id": "1",
                        "attributes": {"status": "paid", "updated_at": "2024-05-01T00:00:00Z"},
                    }
                },
            ]
        )

        result = _webhook_table_transformer(table).to_pylist()

        assert len(result) == 1
        assert result[0]["status"] == "refunded"

    def test_missing_data_column_yields_empty_table(self):
        table = table_from_py_list([{"meta": {"event_name": "order_created"}}])
        assert _webhook_table_transformer(table).num_rows == 0


def _webhook_api_response(status_code: int, body: dict[str, Any] | None = None) -> mock.MagicMock:
    response = mock.MagicMock(status_code=status_code)
    response.json.return_value = body or {}
    response.raise_for_status.return_value = None
    return response


def _list_response(items: list[dict[str, Any]]) -> mock.MagicMock:
    return _webhook_api_response(200, {"data": items, "links": {}})


class TestWebhookManagement:
    @mock.patch(LEMON_SESSION_PATCH)
    def test_create_webhook_creates_one_per_store_with_shared_secret(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _list_response(
            [
                {"type": "stores", "id": "1", "attributes": {}},
                {"type": "stores", "id": "2", "attributes": {}},
            ]
        )
        session.post.return_value = _webhook_api_response(201)

        result = create_webhook("key", "https://us.posthog.com/webhooks/abc")

        assert result.success is True
        secret = result.extra_inputs["signing_secret"]
        assert 6 <= len(secret) <= 40

        assert session.post.call_count == 2
        payloads = [call.kwargs["json"] for call in session.post.call_args_list]
        assert {p["data"]["relationships"]["store"]["data"]["id"] for p in payloads} == {"1", "2"}
        for payload in payloads:
            attributes = payload["data"]["attributes"]
            assert attributes["url"] == "https://us.posthog.com/webhooks/abc"
            assert attributes["events"] == ALL_WEBHOOK_EVENTS
            # A single secret across stores — the hog function only stores one.
            assert attributes["secret"] == secret

    @mock.patch(LEMON_SESSION_PATCH)
    def test_create_webhook_fails_without_stores(self, mock_session):
        mock_session.return_value.get.return_value = _list_response([])

        result = create_webhook("key", "https://us.posthog.com/webhooks/abc")

        assert result.success is False
        assert "manually" in (result.error or "")

    @mock.patch(LEMON_SESSION_PATCH)
    def test_create_webhook_succeeds_when_any_store_succeeds(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _list_response(
            [
                {"type": "stores", "id": "1", "attributes": {}},
                {"type": "stores", "id": "2", "attributes": {}},
            ]
        )
        session.post.side_effect = [_webhook_api_response(201), _webhook_api_response(422)]

        result = create_webhook("key", "https://us.posthog.com/webhooks/abc")

        assert result.success is True
        assert "signing_secret" in result.extra_inputs

    @mock.patch(LEMON_SESSION_PATCH)
    def test_delete_webhook_removes_only_matching_urls(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _list_response(
            [
                {"type": "webhooks", "id": "10", "attributes": {"url": "https://us.posthog.com/webhooks/abc"}},
                {"type": "webhooks", "id": "11", "attributes": {"url": "https://elsewhere.example.com"}},
            ]
        )
        session.delete.return_value = _webhook_api_response(204)

        result = delete_webhook("key", "https://us.posthog.com/webhooks/abc")

        assert result.success is True
        session.delete.assert_called_once()
        assert "/v1/webhooks/10" in session.delete.call_args.args[0]

    @mock.patch(LEMON_SESSION_PATCH)
    def test_get_external_webhook_info(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _list_response(
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

        info = get_external_webhook_info("key", "https://us.posthog.com/webhooks/abc")

        assert info.exists is True
        assert info.enabled_events == ["order_created"]

    @mock.patch(LEMON_SESSION_PATCH)
    def test_get_external_webhook_info_not_found(self, mock_session):
        mock_session.return_value.get.return_value = _list_response([])

        info = get_external_webhook_info("key", "https://us.posthog.com/webhooks/abc")

        assert info.exists is False

    @mock.patch(LEMON_SESSION_PATCH)
    def test_sync_webhook_events_merges_missing_events(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _list_response(
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
        )
        session.patch.return_value = _webhook_api_response(200)

        result = sync_webhook_events("key", "https://us.posthog.com/webhooks/abc", ["order_created", "order_refunded"])

        assert result.success is True
        payload = session.patch.call_args.kwargs["json"]
        # Desired events are added; manually-added extras are preserved.
        assert payload["data"]["attributes"]["events"] == ["custom_extra_event", "order_created", "order_refunded"]

    @mock.patch(LEMON_SESSION_PATCH)
    def test_sync_webhook_events_skips_patch_when_already_subscribed(self, mock_session):
        session = mock_session.return_value
        session.get.return_value = _list_response(
            [
                {
                    "type": "webhooks",
                    "id": "10",
                    "attributes": {"url": "https://us.posthog.com/webhooks/abc", "events": ["order_created"]},
                },
            ]
        )

        result = sync_webhook_events("key", "https://us.posthog.com/webhooks/abc", ["order_created"])

        assert result.success is True
        session.patch.assert_not_called()


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

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.lemon_squeezy.rest_api_resource"
    )
    def test_source_pins_host_and_disables_capture(self, mock_rest_api_resource):
        _source("orders", _make_manager())

        client = mock_rest_api_resource.call_args.args[0]["client"]
        # Off-host next/resume URLs and redirects are rejected before the bearer token is sent.
        assert client["allowed_hosts"] == []
        assert client["allow_redirects"] is False
        # Response bodies carry PII, license keys, and signed URLs — never captured as samples.
        assert _adapter_capture(client["session"]) is False

    def test_make_session_disables_capture(self):
        # Webhook responses carry the signing secret and store/customer data.
        assert _adapter_capture(_make_session("key")) is False


def _adapter_capture(session: Any) -> bool:
    adapter = session.get_adapter(BASE_URL)
    assert isinstance(adapter, TrackedHTTPAdapter)
    return adapter._capture
