from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, cast

from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uppromote import (
    UpPromoteSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.settings import UPPROMOTE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.source import UpPromoteSource
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.uppromote import (
    UpPromoteResumeConfig,
    _build_resource,
    _format_datetime,
    _make_webhook_table_transformer,
    _window_start,
    all_desired_webhook_events,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    sync_webhook_events,
    validate_credentials,
)

WEBHOOK_URL = "https://hooks.posthog.com/uppromote"


def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"status": 200, "message": "success", "data": rows})


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


def _driver() -> SourceDriver:
    return SourceDriver(UpPromoteSource(), UpPromoteSourceConfig(api_key="test-key"))


class TestDatetimeHelpers:
    @parameterized.expand(
        [
            ("datetime_naive", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            ("datetime_aware", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            ("date", date(2026, 1, 2), "2026-01-02T00:00:00Z"),
        ]
    )
    def test_format_datetime(self, _label: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected

    @parameterized.expand(
        [
            # The window start re-reads one second before the watermark so an exclusive
            # `from_date` can't skip boundary rows.
            ("iso_string", "2026-01-01T00:00:10Z", "2026-01-01T00:00:09Z"),
            ("datetime", datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC), "2025-12-31T23:59:59Z"),
            ("unparseable", "not-a-date", None),
            ("unsupported_type", 12345, None),
        ]
    )
    def test_window_start(self, _label: str, value: Any, expected: str | None) -> None:
        assert _window_start(value) == expected


class TestBuildResource:
    @parameterized.expand([(name,) for name in UPPROMOTE_ENDPOINTS])
    def test_every_endpoint_builds_a_resource_with_data_selector(self, endpoint: str) -> None:
        resource = _build_resource(
            UPPROMOTE_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            window_end="2026-02-01T00:00:00Z",
        )
        assert resource["name"] == endpoint
        assert _endpoint(resource)["data_selector"] == "data"
        assert resource["table_format"] == "delta"


class TestUpPromoteSourcePagination:
    def test_resume_reuses_frozen_referral_window_end(self) -> None:
        result = _driver().run(
            "referrals",
            [_page([{"id": 1}]), _page([])],
            resume_state=UpPromoteResumeConfig(page=3, to_date="2026-02-01T00:00:00Z"),
            incremental_field="created_at",
            db_incremental_field_last_value="2026-01-01T00:00:10Z",
        )

        assert result.params("page") == ["3", "4"]
        assert result.params("to_date") == ["2026-02-01T00:00:00Z"] * 2
        assert result.params("from_date") == ["2026-01-01T00:00:09Z"] * 2

        # The frozen window end is carried into subsequent checkpoints too.
        assert result.saved_states
        assert all(state.to_date == "2026-02-01T00:00:00Z" for state in result.saved_states)

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("referrals", [_page([])])

        assert result.params("page") == ["1"]

    @parameterized.expand(
        [
            # Both endpoints reject `from_date` without `to_date` with a 422.
            ("referrals", "created_at", "2026-01-01T00:00:10Z", "2026-01-01T00:00:09Z", True),
            ("connected_customers", "connection_date", "2026-01-01T00:00:10Z", "2026-01-01T00:00:09Z", True),
            ("affiliates", "created_at", "2026-01-01T00:00:10Z", "2026-01-01T00:00:09Z", False),
            # A first incremental run has no watermark and pulls everything.
            ("connected_customers", "connection_date", None, None, False),
        ]
    )
    def test_incremental_window_params(
        self,
        endpoint: str,
        incremental_field: str,
        last_value: str | None,
        expected_from_date: str | None,
        expects_to_date: bool,
    ) -> None:
        result = _driver().run(
            endpoint,
            [_page([{"id": 1}]), _page([])],
            incremental_field=incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert result.params("page") == ["1", "2"]
        assert result.params("from_date") == [expected_from_date] * 2
        to_dates = result.params("to_date")
        if expects_to_date:
            assert to_dates[0] is not None
            # The window end stays frozen across the pages of one run.
            assert to_dates == [to_dates[0]] * 2
        else:
            assert to_dates == [None, None]

    def test_full_refresh_sends_no_window(self) -> None:
        result = _driver().run("connected_customers", [_page([{"affiliate_id": 1}]), _page([])])

        assert result.params("from_date") == [None, None]
        assert result.params("to_date") == [None, None]

    @parameterized.expand(
        [
            ("programs", ["id"]),
            ("affiliates", ["id"]),
            ("coupons", ["id"]),
            ("referrals", ["id"]),
            ("payments_paid", ["payment_id"]),
            ("payments_unpaid", ["affiliate_id"]),
        ]
    )
    def test_source_response_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys
        # Ordering is undocumented, so the watermark must only commit on completed syncs.
        assert result.response.sort_mode == "desc"

    def test_webhook_enabled_run_reads_webhook_items_instead_of_pulling(self) -> None:
        webhook_manager = MagicMock(spec=WebhookSourceManager)
        webhook_manager.webhook_enabled = AsyncMock(return_value=True)

        with patch.object(UpPromoteSource, "get_webhook_source_manager", return_value=webhook_manager):
            result = _driver().run("referrals", [])

        assert result.requests == []
        webhook_manager.get_items.assert_called_once()
        assert "table_transformer" in webhook_manager.get_items.call_args.kwargs


class TestProgramExcludedFanout:
    def test_fans_out_over_every_program_page_and_tags_rows_with_the_program(self) -> None:
        result = _driver().run(
            "program_excluded",
            route(
                {
                    "/programs": [_page([{"id": 11}, {"id": 12}]), _page([{"id": 13}]), _page([])],
                    "/programs/11/excluded": [
                        ScriptedResponse(
                            json={
                                "status": 200,
                                "message": "success",
                                "data": {"apply_to": "products", "apply_to_ids": ["9001", "9002"]},
                            }
                        )
                    ],
                    # A program without exclusions returns no object and produces no row.
                    "/programs/12/excluded": [_page([])],
                    "/programs/13/excluded": [
                        ScriptedResponse(
                            json={
                                "status": 200,
                                "message": "success",
                                "data": {"apply_to": "collections", "apply_to_ids": []},
                            }
                        )
                    ],
                }
            ),
        )

        assert result.raised is None
        assert sorted(result.rows, key=lambda row: row["program_id"]) == [
            {"program_id": 11, "apply_to": "products", "apply_to_ids": ["9001", "9002"]},
            {"program_id": 13, "apply_to": "collections", "apply_to_ids": []},
        ]

        child_requests = [request for request in result.requests if request.path.endswith("/excluded")]
        assert [request.path for request in child_requests] == [
            "/api/v2/programs/11/excluded",
            "/api/v2/programs/12/excluded",
            "/api/v2/programs/13/excluded",
        ]
        # The child endpoint is a single object, so it must not be paginated.
        assert all(request.param("page") is None for request in child_requests)
        assert all(request.param("per_page") is None for request in child_requests)

        parent_requests = [request for request in result.requests if request.path == "/api/v2/programs"]
        assert [request.param("page") for request in parent_requests] == ["1", "2", "3"]
        assert all(request.headers["authorization"] == "test-key" for request in result.requests)


class TestWebhookTableTransformer:
    def test_keeps_latest_row_per_key_and_drops_keyless_rows(self) -> None:
        transform = _make_webhook_table_transformer("id")
        table = table_from_py_list(
            [
                {"id": 1, "status": "pending"},
                {"id": 2, "status": "pending"},
                # Arrival order is oldest-first, so the later row is the newer version.
                {"id": 1, "status": "approved"},
                {"id": None, "status": "ignored"},
            ]
        )

        result = transform(table)
        rows = {row["id"]: row for row in result.to_pylist()}

        assert set(rows.keys()) == {1, 2}
        assert rows[1]["status"] == "approved"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, {"status": 200, "message": "success", "data": []}, True),
        ]
    )
    def test_status_mapping(self, _label: str, status_code: int, body: dict[str, Any], expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json=body))) as network:
            valid, error = validate_credentials("test-key")

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error
        assert network.requests_log[0].path == "/api/v2/affiliates"
        assert network.requests_log[0].headers["authorization"] == "test-key"


def _subscription(event: str, target_url: str = WEBHOOK_URL, secret: str | None = "sec-1") -> dict[str, Any]:
    return {
        "event": event,
        "target_url": target_url,
        "status": "active",
        "secret_key": secret,
        "created_at": "2026-01-01T00:00:00Z",
    }


def _subscriptions_api(
    listed: list[dict[str, Any]], created: dict[str, Any] | None = None, status: int = 200
) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.method == "GET":
            return ScriptedResponse(
                status=status, json={"data": listed} if status == 200 else {"message": "Unauthorized"}
            )
        if request.method == "POST":
            return ScriptedResponse(json={"data": created or {}})
        return ScriptedResponse(json={"status": 200, "message": "success"})

    return respond


def _events_sent(requests_log: list[RecordedRequest], method: str) -> list[str]:
    return [request.json()["event"] for request in requests_log if request.method == method]


class TestWebhookManagement:
    def test_create_webhook_subscribes_every_desired_event(self) -> None:
        with scripted_network(_subscriptions_api([], created={"secret_key": "sec-9"})) as network:
            result = create_webhook("test-key", WEBHOOK_URL)

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "sec-9"}
        assert result.pending_inputs == []

        assert set(_events_sent(network.requests_log, "POST")) == set(all_desired_webhook_events())

    def test_create_webhook_fails_when_every_event_is_taken(self) -> None:
        taken = [_subscription(event, target_url="https://elsewhere.example") for event in all_desired_webhook_events()]
        with scripted_network(_subscriptions_api(taken)) as network:
            result = create_webhook("test-key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "one subscription per event" in result.error
        assert _events_sent(network.requests_log, "POST") == []

    def test_create_webhook_without_secret_reports_pending_input(self) -> None:
        with scripted_network(_subscriptions_api([])):
            result = create_webhook("test-key", WEBHOOK_URL)

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]

    def test_create_webhook_surfaces_api_errors(self) -> None:
        with scripted_network(_subscriptions_api([], status=401)):
            result = create_webhook("test-key", WEBHOOK_URL)

        assert result.success is False
        assert result.error == "Unauthorized"

    def test_sync_webhook_events_resubscribes_missing_events(self) -> None:
        with scripted_network(
            _subscriptions_api([_subscription("referral.new")], created={"secret_key": "sec-1"})
        ) as network:
            result = sync_webhook_events("test-key", WEBHOOK_URL, ["referral.new", "referral.approved"])

        assert result.success is True
        assert set(_events_sent(network.requests_log, "POST")) == {"referral.approved"}

    def test_sync_webhook_events_reports_events_taken_by_other_urls(self) -> None:
        with scripted_network(
            _subscriptions_api([_subscription("referral.new", target_url="https://elsewhere.example")])
        ):
            result = sync_webhook_events("test-key", WEBHOOK_URL, ["referral.new"])

        assert result.success is False
        assert result.error is not None and "referral.new" in result.error

    def test_get_external_webhook_info_reports_our_subscriptions(self) -> None:
        with scripted_network(
            _subscriptions_api(
                [
                    _subscription("referral.new"),
                    _subscription("affiliate.new"),
                    _subscription("payment.paid", target_url="https://elsewhere.example"),
                ]
            )
        ):
            info = get_external_webhook_info("test-key", WEBHOOK_URL)

        assert info.exists is True
        assert info.enabled_events == ["affiliate.new", "referral.new"]
        assert info.status == "active"

    def test_get_external_webhook_info_when_nothing_points_at_us(self) -> None:
        with scripted_network(_subscriptions_api([])):
            info = get_external_webhook_info("test-key", WEBHOOK_URL)

        assert info.exists is False

    def test_delete_webhook_removes_only_our_subscriptions(self) -> None:
        with scripted_network(
            _subscriptions_api(
                [
                    _subscription("referral.new"),
                    _subscription("payment.paid", target_url="https://elsewhere.example"),
                ]
            )
        ) as network:
            result = delete_webhook("test-key", WEBHOOK_URL)

        assert result.success is True
        assert _events_sent(network.requests_log, "DELETE") == ["referral.new"]

    def test_delete_webhook_with_no_matching_subscription_fails(self) -> None:
        with scripted_network(_subscriptions_api([])) as network:
            result = delete_webhook("test-key", WEBHOOK_URL)

        assert result.success is False
        assert _events_sent(network.requests_log, "DELETE") == []
