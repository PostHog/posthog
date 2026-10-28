import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.fourthwall import (
    FourthwallResumeConfig,
    _format_datetime,
    create_webhook,
    delete_webhook,
    fourthwall_source,
    get_external_webhook_info,
    get_resource,
    sync_webhook_events,
    validate_credentials,
    webhook_table_transformer,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.settings import (
    ALL_WEBHOOK_EVENTS,
    ENDPOINTS,
    FOURTHWALL_ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.source import FourthwallSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fourthwall import (
    FourthwallSourceConfig,
)

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.fourthwall.make_tracked_session"
)
API_ROOT = "https://api.fourthwall.com/open-api/v1.0"


def _page(results: list[dict[str, Any]], total_pages: int) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps(
        {"results": results, "total": len(results), "page": 0, "size": PAGE_SIZE, "totalPages": total_pages}
    ).encode()
    return response


def _make_manager(resume_state: FourthwallResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request at prepare time (params mutate per page)."""
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return fourthwall_source(
        "api-user",
        "api-secret",
        endpoint,
        team_id=1,
        job_id="job-1",
        api_version="v1.0",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _order(order_id: str, updated_at: str = "2026-05-01T10:00:00.000Z") -> dict[str, Any]:
    return {"id": order_id, "status": "CONFIRMED", "createdAt": "2026-04-01T10:00:00.000Z", "updatedAt": updated_at}


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 5, 1, 10, 30, 15, 123456, tzinfo=UTC), "2026-05-01T10:30:15Z"),
            # Naive values are treated as UTC, matching the rest of the pipeline.
            (datetime(2026, 5, 1, 10, 30, 15), "2026-05-01T10:30:15Z"),
        ],
    )
    def test_truncates_to_whole_seconds_in_utc(self, value, expected):
        # Rounding the lower bound down re-reads a few boundary orders (merge dedupes them)
        # instead of skipping an order whose updatedAt equals the watermark.
        assert _format_datetime(value) == expected


def _endpoint_config(endpoint: str, should_use_incremental_field: bool = False) -> dict[str, Any]:
    return cast("dict[str, Any]", get_resource(endpoint, should_use_incremental_field)["endpoint"])


class TestGetResource:
    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if not FOURTHWALL_ENDPOINTS[name].paginated])
    def test_bare_array_endpoints_take_no_selector_and_a_single_page(self, endpoint):
        # A `results` selector here would match nothing and sync zero rows.
        endpoint_config = _endpoint_config(endpoint)

        assert "data_selector" not in endpoint_config
        assert endpoint_config["paginator"] == "single_page"

    def test_only_orders_declares_a_server_side_incremental_filter(self):
        # Declaring an incremental param an endpoint doesn't support would send a filter the
        # API ignores, turning every "incremental" sync back into a full scan.
        with_param = {name for name, config in FOURTHWALL_ENDPOINTS.items() if config.incremental_param}
        assert with_param == {"orders"}
        assert FOURTHWALL_ENDPOINTS["orders"].incremental_param == "updatedAt[gt]"


class TestProductTemplatePagination:
    def test_resumes_from_saved_page(self) -> None:
        result = SourceDriver(
            FourthwallSource(), FourthwallSourceConfig(username="api-user", password="api-secret")
        ).run(
            "product_templates",
            [
                ScriptedResponse(json={"results": [{"productId": "pt_9"}], "total": 3}),
                ScriptedResponse(json={"results": [], "total": 3}),
            ],
            resume_state=FourthwallResumeConfig(paginator_state={"page": 4}),
        )

        assert result.raised is None
        assert [row["productId"] for row in result.rows] == ["pt_9"]
        assert result.paths == [
            "/open-api/v1.0/product-templates/page/4",
            "/open-api/v1.0/product-templates/page/5",
        ]


class TestIncrementalRequests:
    @mock.patch(SESSION_PATCH)
    def test_first_incremental_sync_starts_from_the_epoch(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([_order("1")], 1)])

        _rows(_source("orders", _make_manager(), should_use_incremental_field=True))

        assert requests_seen[0]["params"]["updatedAt[gt]"] == "1970-01-01T00:00:00Z"


class TestSourceResponseMetadata:
    def test_orders_finalize_the_watermark_only_after_a_full_sync(self):
        # Fourthwall documents no ordering for the orders list and takes no sort parameter, so
        # `asc` would checkpoint the watermark to whatever the first page happened to contain.
        assert FOURTHWALL_ENDPOINTS["orders"].sort_mode == "desc"

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partition_keys_never_move(self, endpoint):
        # A partition key that changes rewrites partitions on every sync.
        assert FOURTHWALL_ENDPOINTS[endpoint].partition_key in (None, "createdAt")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [(404, False), (429, False)],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, error = validate_credentials("api-user", "api-secret", "v1.0")

        assert is_valid is expected_valid
        assert (error is None) is expected_valid
        assert {request.path for request in network.requests_log} == {"/open-api/v1.0/shops/current"}


class TestWebhookTableTransformer:
    def _table(self, events: list[dict[str, Any]]):
        return table_from_py_list(events)

    def test_keeps_only_the_newest_event_per_object(self):
        # Delta merge dedupes across syncs but not within one batch, so a placed-then-updated
        # pair for the same order has to collapse here.
        table = self._table(
            [
                {
                    "id": "weve_1",
                    "type": "ORDER_PLACED",
                    "createdAt": "2026-05-01T10:00:00+00:00",
                    "data": _order("order_1", updated_at="2026-05-01T10:00:00.000Z"),
                },
                {
                    "id": "weve_2",
                    "type": "ORDER_UPDATED",
                    "createdAt": "2026-05-02T10:00:00+00:00",
                    "data": {"order": _order("order_1", updated_at="2026-05-02T10:00:00.000Z")},
                },
            ]
        )

        rows = webhook_table_transformer(table).to_pylist()

        assert len(rows) == 1
        assert rows[0]["updatedAt"] == "2026-05-02T10:00:00.000Z"

    @pytest.mark.parametrize(
        "event",
        [
            {"id": "weve_1", "type": "ORDER_PLACED", "createdAt": "2026-05-01T10:00:00+00:00", "data": {}},
            {"id": "weve_1", "type": "ORDER_UPDATED", "createdAt": "2026-05-01T10:00:00+00:00", "data": {}},
        ],
    )
    def test_drops_payloads_with_no_object_id(self, event):
        # A row with no primary key would break the merge, so it must never reach the table.
        assert webhook_table_transformer(self._table([event])).num_rows == 0

    def test_empty_delivery_batch_yields_no_rows(self):
        assert webhook_table_transformer(table_from_py_list([{"unexpected": 1}])).num_rows == 0


class TestWebhookManagement:
    @staticmethod
    def _webhook_page(results: list[dict[str, Any]], total_pages: int = 1) -> ScriptedResponse:
        return ScriptedResponse(json={"results": results, "totalPages": total_pages})

    def test_create_webhook_stores_the_returned_secret(self) -> None:
        with scripted_network([ScriptedResponse(json={"id": "wcon_1", "secret": "shhh"})]) as network:
            result = create_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "shhh"}
        assert network.requests_log[0].url == f"{API_ROOT}/webhooks"
        assert network.requests_log[0].method == "POST"
        assert network.requests_log[0].json() == {
            "url": "https://us.posthog.com/w/1",
            "allowedTypes": ALL_WEBHOOK_EVENTS,
        }

    def test_create_webhook_asks_for_the_secret_when_the_response_omits_it(self) -> None:
        # The published webhook schema does not list `secret`, so the user has to paste it;
        # silently succeeding without it would leave every delivery failing the signature check.
        with scripted_network([ScriptedResponse(json={"id": "wcon_1"})]):
            result = create_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]
        assert result.extra_inputs == {}

    @pytest.mark.parametrize("status_code", [400, 401, 429])
    def test_create_webhook_reports_a_rejected_registration(self, status_code: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))):
            result = create_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is False
        assert result.error is not None

    def test_sync_webhook_events_merges_instead_of_replacing(self) -> None:
        # Replacing would wipe events a user added by hand in the Fourthwall dashboard.
        with scripted_network(
            [
                self._webhook_page(
                    [{"id": "wcon_1", "url": "https://us.posthog.com/w/1", "allowedTypes": ["THANK_YOU_SENT"]}]
                ),
                ScriptedResponse(),
            ]
        ) as network:
            result = sync_webhook_events(
                "api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1", ["ORDER_PLACED"]
            )

        assert result.success is True
        assert network.requests_log[1].method == "PUT"
        assert network.requests_log[1].json() == {
            "url": "https://us.posthog.com/w/1",
            "allowedTypes": ["ORDER_PLACED", "THANK_YOU_SENT"],
        }

    def test_sync_webhook_events_skips_an_already_correct_webhook(self) -> None:
        with scripted_network(
            [
                self._webhook_page(
                    [{"id": "wcon_1", "url": "https://us.posthog.com/w/1", "allowedTypes": ["ORDER_PLACED"]}]
                )
            ]
        ) as network:
            sync_webhook_events("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1", ["ORDER_PLACED"])

        assert [request.method for request in network.requests_log] == ["GET"]

    def test_webhook_lookup_walks_every_page(self) -> None:
        # Stopping after page one would silently skip a shop's webhook and leave a stale
        # registration behind on delete.
        with scripted_network(
            [
                self._webhook_page([{"id": "wcon_1", "url": "https://other", "allowedTypes": []}], total_pages=2),
                self._webhook_page(
                    [{"id": "wcon_2", "url": "https://us.posthog.com/w/1", "allowedTypes": []}], total_pages=2
                ),
                ScriptedResponse(),
            ]
        ) as network:
            result = delete_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is True
        assert [request.param("page") for request in network.requests_log[:2]] == ["0", "1"]
        assert network.requests_log[2].method == "DELETE"
        assert network.requests_log[2].url == f"{API_ROOT}/webhooks/wcon_2"

    def test_delete_webhook_reports_a_failed_deletion(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "GET":
                return self._webhook_page([{"id": "wcon_1", "url": "https://us.posthog.com/w/1", "allowedTypes": []}])
            return ScriptedResponse(status=500)

        with scripted_network(respond) as network:
            result = delete_webhook("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert result.success is False
        assert {request.path for request in network.requests_log} == {
            "/open-api/v1.0/webhooks",
            "/open-api/v1.0/webhooks/wcon_1",
        }

    def test_external_webhook_info_matches_on_url(self) -> None:
        with scripted_network(
            [
                self._webhook_page(
                    [
                        {"id": "wcon_1", "url": "https://elsewhere", "allowedTypes": ["DONATION"]},
                        {"id": "wcon_2", "url": "https://us.posthog.com/w/1", "allowedTypes": ["ORDER_PLACED"]},
                    ]
                )
            ]
        ):
            info = get_external_webhook_info("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1")

        assert info.exists is True
        assert info.enabled_events == ["ORDER_PLACED"]

    def test_external_webhook_info_when_absent(self) -> None:
        with scripted_network([self._webhook_page([])]):
            assert (
                get_external_webhook_info("api-user", "api-secret", "v1.0", "https://us.posthog.com/w/1").exists
                is False
            )

    def test_webhook_helpers_surface_transport_failures(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            error = get_external_webhook_info("api-user", "api-secret", "v1.0", "https://u/1").error
            assert error is not None and "boom" in error
        with scripted_network(always(ConnectionError("boom"))):
            assert sync_webhook_events("api-user", "api-secret", "v1.0", "https://u/1", []).success is False
        with scripted_network(always(ConnectionError("boom"))):
            assert delete_webhook("api-user", "api-secret", "v1.0", "https://u/1").success is False
