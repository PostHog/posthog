import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.settings import (
    UPPROMOTE_ENDPOINTS,
    UPPROMOTE_PAGE_SIZE,
)
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
    uppromote_source,
    validate_credentials,
)

TRANSPORT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.uppromote"

WEBHOOK_URL = "https://hooks.posthog.com/uppromote"


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://aff-api.uppromote.com/api/v2/test"
    return resp


def _page(rows: list[dict[str, Any]]) -> Response:
    return _make_http_response({"status": 200, "message": "success", "data": rows})


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


def _make_webhook_manager(enabled: bool = False) -> MagicMock:
    manager = MagicMock()
    manager.webhook_enabled = AsyncMock(return_value=enabled)
    return manager


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
    def test_incremental_run_sends_creation_window(self) -> None:
        resource = _build_resource(
            UPPROMOTE_ENDPOINTS["affiliates"],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:10Z",
            window_end="2026-02-01T00:00:00Z",
        )
        params = _endpoint(resource)["params"]
        assert params["from_date"] == "2026-01-01T00:00:09Z"
        # Only referrals require the paired to_date; other endpoints filter with from_date alone.
        assert "to_date" not in params
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    def test_referrals_send_from_and_to_date_together(self) -> None:
        resource = _build_resource(
            UPPROMOTE_ENDPOINTS["referrals"],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:10Z",
            window_end="2026-02-01T00:00:00Z",
        )
        params = _endpoint(resource)["params"]
        assert params["from_date"] == "2026-01-01T00:00:09Z"
        assert params["to_date"] == "2026-02-01T00:00:00Z"

    def test_first_incremental_run_sends_no_window(self) -> None:
        resource = _build_resource(
            UPPROMOTE_ENDPOINTS["referrals"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            window_end="2026-02-01T00:00:00Z",
        )
        params = _endpoint(resource)["params"]
        assert "from_date" not in params
        assert "to_date" not in params

    def test_full_refresh_replaces_and_sends_no_window(self) -> None:
        resource = _build_resource(
            UPPROMOTE_ENDPOINTS["affiliates"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            window_end="2026-02-01T00:00:00Z",
        )
        params = _endpoint(resource)["params"]
        assert params == {"per_page": UPPROMOTE_PAGE_SIZE}
        assert resource["write_disposition"] == "replace"

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
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
        """Drive ``uppromote_source`` with a mocked HTTP session.

        Returns ``(sent_params, yielded_pages)``. Params are captured at send-time because the
        paginator mutates the Request in place between pages.
        """
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        # The pull path builds its own capture-disabled session and hands it to RESTClient
        # via config, so patch the factory where the source imports it.
        with patch(f"{TRANSPORT_MODULE}.make_tracked_session") as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source = uppromote_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                webhook_source_manager=_make_webhook_manager(enabled=False),
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
            pages = list(cast(Iterable[list[dict[str, Any]]], source.items()))
            return sent_params, pages

    def test_paginates_until_empty_page_and_saves_resume_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _page([{"id": 1}]),
            _page([{"id": 2}]),
            _page([]),
        ]
        sent_params, pages = self._drive("affiliates", manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2, 3]
        assert all(p.get("per_page") == UPPROMOTE_PAGE_SIZE for p in sent_params)
        # The terminal empty page only stops pagination; it is not yielded as a batch.
        assert pages == [[{"id": 1}], [{"id": 2}]]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert [state.page for state in saved] == [2, 3]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = UpPromoteResumeConfig(page=5)

        sent_params, _ = self._drive("affiliates", manager, [_page([])])

        assert [p.get("page") for p in sent_params] == [5]
        manager.load_state.assert_called_once()

    def test_resume_reuses_frozen_referral_window_end(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = UpPromoteResumeConfig(page=3, to_date="2026-02-01T00:00:00Z")

        sent_params, _ = self._drive(
            "referrals",
            manager,
            [_page([{"id": 1}]), _page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:10Z",
        )

        assert [p.get("page") for p in sent_params] == [3, 4]
        assert all(p.get("to_date") == "2026-02-01T00:00:00Z" for p in sent_params)
        assert all(p.get("from_date") == "2026-01-01T00:00:09Z" for p in sent_params)

        # The frozen window end is carried into subsequent checkpoints too.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert all(state.to_date == "2026-02-01T00:00:00Z" for state in saved)

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        self._drive("affiliates", manager, [_page([])])

        manager.save_state.assert_not_called()

    def test_pull_session_disables_http_sample_capture(self) -> None:
        # Affiliate/referral sync bodies carry PII, so the pull path must never let RESTClient
        # capture raw responses into the shared samples prefix.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session") as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = lambda *_a, **_k: _page([])

            source = uppromote_source(
                api_key="test-key",
                endpoint="affiliates",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                webhook_source_manager=_make_webhook_manager(enabled=False),
            )
            list(cast(Iterable[list[dict[str, Any]]], source.items()))

        assert all(call.kwargs.get("capture") is False for call in MockSession.call_args_list)
        assert MockSession.call_args_list, "expected the pull path to build a tracked session"

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
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        source = uppromote_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            webhook_source_manager=_make_webhook_manager(enabled=False),
        )

        assert source.name == endpoint
        assert source.primary_keys == expected_keys
        # Ordering is undocumented, so the watermark must only commit on completed syncs.
        assert source.sort_mode == "desc"

    def test_webhook_enabled_run_reads_webhook_items_instead_of_pulling(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        webhook_manager = _make_webhook_manager(enabled=True)

        source = uppromote_source(
            api_key="test-key",
            endpoint="referrals",
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            webhook_source_manager=webhook_manager,
        )
        source.items()

        webhook_manager.get_items.assert_called_once()
        assert "table_transformer" in webhook_manager.get_items.call_args.kwargs


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

    def test_payment_rows_dedupe_on_payment_id(self) -> None:
        transform = _make_webhook_table_transformer("payment_id")
        table = table_from_py_list(
            [
                {"payment_id": 7, "status": "PENDING"},
                {"payment_id": 7, "status": "SUCCESS"},
            ]
        )

        result = transform(table)

        assert result.to_pylist() == [{"payment_id": 7, "status": "SUCCESS"}]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, {"status": 200, "message": "success", "data": []}, True),
            ("unauthorized", 401, {"message": "Unauthorized"}, False),
            ("server_error", 500, {"message": "Error"}, False),
        ]
    )
    def test_status_mapping(self, _label: str, status_code: int, body: dict[str, Any], expected_valid: bool) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response(body, status_code=status_code)

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            valid, error = validate_credentials("test-key")

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error

    def test_network_failure_is_reported_not_raised(self) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            valid, error = validate_credentials("test-key")

        assert valid is False
        assert error is not None and "Could not reach UpPromote" in error


def _subscription(event: str, target_url: str = WEBHOOK_URL, secret: str | None = "sec-1") -> dict[str, Any]:
    return {
        "event": event,
        "target_url": target_url,
        "status": "active",
        "secret_key": secret,
        "created_at": "2026-01-01T00:00:00Z",
    }


class TestWebhookManagement:
    def test_create_webhook_subscribes_every_desired_event(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response({"data": []})
        session.post.return_value = _make_http_response({"data": {"secret_key": "sec-9"}})

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            result = create_webhook("test-key", WEBHOOK_URL)

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "sec-9"}
        assert result.pending_inputs == []

        posted_events = {call.kwargs["json"]["event"] for call in session.post.call_args_list}
        assert posted_events == set(all_desired_webhook_events())

    def test_create_webhook_reuses_existing_own_subscriptions(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response(
            {"data": [_subscription(event) for event in all_desired_webhook_events()]}
        )

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            result = create_webhook("test-key", WEBHOOK_URL)

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "sec-1"}
        session.post.assert_not_called()

    def test_create_webhook_fails_when_every_event_is_taken(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response(
            {
                "data": [
                    _subscription(event, target_url="https://elsewhere.example")
                    for event in all_desired_webhook_events()
                ]
            }
        )

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            result = create_webhook("test-key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "one subscription per event" in result.error
        session.post.assert_not_called()

    def test_create_webhook_without_secret_reports_pending_input(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response({"data": []})
        session.post.return_value = _make_http_response({"data": {}})

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            result = create_webhook("test-key", WEBHOOK_URL)

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]

    def test_create_webhook_surfaces_api_errors(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response({"message": "Unauthorized"}, status_code=401)

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            result = create_webhook("test-key", WEBHOOK_URL)

        assert result.success is False
        assert result.error == "Unauthorized"

    def test_sync_webhook_events_resubscribes_missing_events(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response({"data": [_subscription("referral.new")]})
        session.post.return_value = _make_http_response({"data": {"secret_key": "sec-1"}})

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            result = sync_webhook_events("test-key", WEBHOOK_URL, ["referral.new", "referral.approved"])

        assert result.success is True
        posted_events = {call.kwargs["json"]["event"] for call in session.post.call_args_list}
        assert posted_events == {"referral.approved"}

    def test_sync_webhook_events_reports_events_taken_by_other_urls(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response(
            {"data": [_subscription("referral.new", target_url="https://elsewhere.example")]}
        )

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            result = sync_webhook_events("test-key", WEBHOOK_URL, ["referral.new"])

        assert result.success is False
        assert result.error is not None and "referral.new" in result.error

    def test_get_external_webhook_info_reports_our_subscriptions(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response(
            {
                "data": [
                    _subscription("referral.new"),
                    _subscription("affiliate.new"),
                    _subscription("payment.paid", target_url="https://elsewhere.example"),
                ]
            }
        )

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            info = get_external_webhook_info("test-key", WEBHOOK_URL)

        assert info.exists is True
        assert info.enabled_events == ["affiliate.new", "referral.new"]
        assert info.status == "active"

    def test_get_external_webhook_info_when_nothing_points_at_us(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response({"data": []})

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            info = get_external_webhook_info("test-key", WEBHOOK_URL)

        assert info.exists is False

    def test_delete_webhook_removes_only_our_subscriptions(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response(
            {
                "data": [
                    _subscription("referral.new"),
                    _subscription("payment.paid", target_url="https://elsewhere.example"),
                ]
            }
        )
        session.delete.return_value = _make_http_response({"status": 200, "message": "success"})

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            result = delete_webhook("test-key", WEBHOOK_URL)

        assert result.success is True
        deleted_events = [call.kwargs["json"]["event"] for call in session.delete.call_args_list]
        assert deleted_events == ["referral.new"]

    def test_delete_webhook_with_no_matching_subscription_fails(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_http_response({"data": []})

        with patch(f"{TRANSPORT_MODULE}._make_session", return_value=session):
            result = delete_webhook("test-key", WEBHOOK_URL)

        assert result.success is False
        session.delete.assert_not_called()
