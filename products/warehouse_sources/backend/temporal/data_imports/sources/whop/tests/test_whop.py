import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.settings import (
    ALL_WEBHOOK_EVENTS,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    WHOP_ENDPOINTS,
    sort_mode_for,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.whop import (
    WhopCursorPaginator,
    WhopResumeConfig,
    _list_params,
    _parse_datetime,
    _to_iso8601,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    sync_webhook_events,
    validate_credentials,
    webhook_table_transformer,
    whop_source,
)

# The source builds its own capture-disabled tracked session for the sync client, the credential
# probe, and the webhook management helpers.
WHOP_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.whop.whop.make_tracked_session"
REST_RESOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.whop.whop.rest_api_resource"

COMPANY_ID = "biz_test"


def _page(items: list[dict[str, Any]], end_cursor: str | None, has_next_page: bool) -> Response:
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
    response = Response()
    response.status_code = 200
    response._content = json.dumps(body).encode()
    return response


def _make_manager(resume_state: WhopResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request at prepare time (params mutate across pages)."""
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
    return whop_source(
        "test-api-key",
        COMPANY_ID,
        endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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

    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 5, 1, 10, tzinfo=UTC), "2024-05-01T10:00:00.000Z"),
            (datetime(2024, 5, 1, 10, 0, 0, 401000, tzinfo=UTC), "2024-05-01T10:00:00.401Z"),
        ],
    )
    def test_iso8601_uses_z_suffix(self, value, expected):
        # Whop's timestamp filters document a `Z`-suffixed ISO 8601 value; `+00:00` is not accepted
        # by every vendor and there is no reason to risk it.
        assert _to_iso8601(value) == expected


class TestListParams:
    def test_ordered_endpoint_forces_ascending_created_at(self):
        # Only a forced sort column makes the arrival order knowable, which is what lets these
        # endpoints declare sort_mode="asc" and checkpoint the watermark per batch.
        params = _list_params("payments", COMPANY_ID, None)
        assert params["order"] == "created_at"
        assert params["direction"] == "asc"

    def test_direction_only_endpoint_pins_descending_and_sends_no_order(self):
        # `/refunds` has no `order` enum, so sending one would 400; the sort column is undocumented
        # so the endpoint is declared desc and the watermark deferred.
        params = _list_params("refunds", COMPANY_ID, None)
        assert params["direction"] == "desc"
        assert "order" not in params

    def test_endpoint_without_sort_params_sends_neither(self):
        params = _list_params("promo_codes", COMPANY_ID, None)
        assert "order" not in params
        assert "direction" not in params

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_company_and_page_size_always_sent(self, endpoint):
        params = _list_params(endpoint, COMPANY_ID, None)
        assert params["company_id"] == COMPANY_ID
        assert params["first"] == PAGE_SIZE

    def test_watermark_becomes_server_side_created_after(self):
        params = _list_params("payments", COMPANY_ID, datetime(2024, 5, 1, 10, tzinfo=UTC))
        assert params["created_after"] == "2024-05-01T10:00:00.000Z"

    def test_full_refresh_sends_no_created_after(self):
        assert "created_after" not in _list_params("payments", COMPANY_ID, None)

    @pytest.mark.parametrize(
        "endpoint",
        [name for name, config in WHOP_ENDPOINTS.items() if not config.supports_created_after],
    )
    def test_endpoints_without_the_filter_never_send_created_after(self, endpoint):
        # These resources carry no trackable `created_at`; sending the filter would silently drop
        # rows the pipeline would then never backfill.
        assert "created_after" not in _list_params(endpoint, COMPANY_ID, datetime(2024, 5, 1, tzinfo=UTC))


class TestPagination:
    @mock.patch(WHOP_SESSION_PATCH)
    def test_follows_end_cursor_and_saves_resume_state(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                _page([{"id": "pay_1"}], end_cursor="cursor-1", has_next_page=True),
                _page([{"id": "pay_2"}], end_cursor="cursor-2", has_next_page=False),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("payments", manager))

        assert [row["id"] for row in rows] == ["pay_1", "pay_2"]
        assert "after" not in requests_seen[0]["params"]
        assert requests_seen[1]["params"]["after"] == "cursor-1"
        # State is persisted only while a next page remains, after the page was yielded.
        manager.save_state.assert_called_once_with(WhopResumeConfig(cursor="cursor-1"))

    @mock.patch(WHOP_SESSION_PATCH)
    def test_stops_when_has_next_page_is_false_despite_a_populated_cursor(self, MockSession):
        # Relay keeps `end_cursor` set on the last page, so a cursor-only stop condition would
        # re-request the final page forever.
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([{"id": "pay_1"}], end_cursor="cursor-1", has_next_page=False)])

        manager = _make_manager()
        rows = _rows(_source("payments", manager))

        assert len(requests_seen) == 1
        assert [row["id"] for row in rows] == ["pay_1"]
        manager.save_state.assert_not_called()

    @mock.patch(WHOP_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([{"id": "pay_9"}], end_cursor="cursor-9", has_next_page=False)])

        rows = _rows(_source("payments", _make_manager(WhopResumeConfig(cursor="cursor-8"))))

        assert [row["id"] for row in rows] == ["pay_9"]
        assert requests_seen[0]["params"]["after"] == "cursor-8"

    @pytest.mark.parametrize(
        "page_info, expected_has_next",
        [
            ({"end_cursor": "c", "has_next_page": True}, True),
            ({"end_cursor": "c", "has_next_page": False}, False),
            ({"end_cursor": None, "has_next_page": True}, False),
            ({}, False),
        ],
    )
    def test_paginator_termination(self, page_info, expected_has_next):
        response = Response()
        response.status_code = 200
        response._content = json.dumps({"data": [], "page_info": page_info}).encode()

        paginator = WhopCursorPaginator()
        paginator.update_state(response, [])

        assert paginator.has_next_page is expected_has_next

    def test_paginator_stops_on_unparseable_body(self):
        # Nothing to page with, so stopping beats re-requesting the same cursor forever.
        response = Response()
        response.status_code = 200
        response._content = b"not json"

        paginator = WhopCursorPaginator()
        paginator.update_state(response, [])

        assert paginator.has_next_page is False


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(WHOP_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == sort_mode_for(endpoint)

        partition_key = WHOP_ENDPOINTS[endpoint].partition_key
        if partition_key is None:
            # Partitioning on a column the resource does not return would key every row to null.
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    @pytest.mark.parametrize(
        "should_use_incremental_field, expected_disposition",
        [
            (True, {"disposition": "merge", "strategy": "upsert"}),
            (False, "replace"),
        ],
    )
    @mock.patch(REST_RESOURCE_PATCH)
    @mock.patch(WHOP_SESSION_PATCH)
    def test_write_disposition_follows_incremental_mode(
        self, MockSession, mock_rest_api_resource, should_use_incremental_field, expected_disposition
    ):
        _source("payments", _make_manager(), should_use_incremental_field=should_use_incremental_field)

        config = mock_rest_api_resource.call_args.args[0]
        assert config["resources"][0]["write_disposition"] == expected_disposition

    @mock.patch(REST_RESOURCE_PATCH)
    @mock.patch(WHOP_SESSION_PATCH)
    def test_framework_incremental_injection_is_not_used(self, MockSession, mock_rest_api_resource):
        # `created_after` is baked into the request params; letting the framework also inject the
        # watermark would add a second, wrongly-named filter param.
        _source(
            "payments",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01T10:00:00Z",
        )

        assert mock_rest_api_resource.call_args.kwargs["db_incremental_field_last_value"] is None
        params = mock_rest_api_resource.call_args.args[0]["resources"][0]["endpoint"]["params"]
        assert params["created_after"] == "2024-05-01T10:00:00.000Z"


class TestWebhookTableTransformer:
    def test_hoists_data_and_keeps_latest_delivery_per_id(self):
        table = table_from_py_list(
            [
                {
                    "id": "msg_1",
                    "type": "payment.pending",
                    "timestamp": "2024-05-01T00:00:00Z",
                    "data": {"id": "pay_1", "status": "open"},
                },
                {
                    "id": "msg_2",
                    "type": "payment.succeeded",
                    "timestamp": "2024-05-02T00:00:00Z",
                    "data": {"id": "pay_1", "status": "paid"},
                },
                {
                    "id": "msg_3",
                    "type": "payment.succeeded",
                    "timestamp": "2024-05-01T00:00:00Z",
                    "data": {"id": "pay_2", "status": "paid"},
                },
            ]
        )

        rows = webhook_table_transformer(table).to_pylist()

        assert sorted(rows, key=lambda row: row["id"]) == [
            {"id": "pay_1", "status": "paid"},
            {"id": "pay_2", "status": "paid"},
        ]

    def test_accepts_payloads_serialized_back_to_json_strings(self):
        table = table_from_py_list(
            [{"id": "msg_1", "timestamp": "2024-05-01T00:00:00Z", "data": json.dumps({"id": "pay_1", "total": 10})}]
        )

        assert webhook_table_transformer(table).to_pylist() == [{"id": "pay_1", "total": 10}]

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
    @pytest.mark.parametrize(
        "status_code, expected",
        [(200, (True, 200)), (401, (False, 401)), (403, (False, 403)), (404, (False, 404)), (500, (False, 500))],
    )
    @mock.patch(WHOP_SESSION_PATCH)
    def test_status_mapping(self, MockSession, status_code, expected):
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key", COMPANY_ID) == expected

    @mock.patch(WHOP_SESSION_PATCH)
    def test_probes_the_connected_company_with_a_bearer_token(self, MockSession):
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key", COMPANY_ID)

        call = MockSession.return_value.get.call_args
        assert call.args[0] == f"{BASE_URL}/companies/{COMPANY_ID}"
        assert call.kwargs["headers"]["Authorization"] == "Bearer key"

    @mock.patch(WHOP_SESSION_PATCH)
    def test_transport_failure_never_raises(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", COMPANY_ID) == (False, None)


def _json_response(status_code: int, body: Any) -> mock.MagicMock:
    response = mock.MagicMock(status_code=status_code)
    response.json.return_value = body
    return response


class TestCreateWebhook:
    @mock.patch(WHOP_SESSION_PATCH)
    def test_returns_the_generated_signing_secret(self, MockSession):
        session = MockSession.return_value
        session.post.return_value = _json_response(201, {"id": "hook_1", "webhook_secret": "whsec_abc"})

        result = create_webhook("key", COMPANY_ID, "https://ph.example/webhook")

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "whsec_abc"}
        payload = session.post.call_args.kwargs["json"]
        assert payload["url"] == "https://ph.example/webhook"
        assert payload["resource_id"] == COMPANY_ID
        # Deliveries must use the v1 payload envelope the transformer unwraps.
        assert payload["api_version"] == "v1"
        assert payload["events"] == ALL_WEBHOOK_EVENTS

    @pytest.mark.parametrize("status_code", [401, 403, 422, 500])
    @mock.patch(WHOP_SESSION_PATCH)
    def test_non_success_falls_back_to_manual_setup(self, MockSession, status_code):
        MockSession.return_value.post.return_value = _json_response(status_code, {})

        result = create_webhook("key", COMPANY_ID, "https://ph.example/webhook")

        assert result.success is False
        assert result.error is not None

    @mock.patch(WHOP_SESSION_PATCH)
    def test_missing_secret_is_a_failure(self, MockSession):
        # Without a secret the hog function cannot verify deliveries, so reporting success would
        # silently leave the webhook rejecting every payload.
        MockSession.return_value.post.return_value = _json_response(201, {"id": "hook_1"})

        result = create_webhook("key", COMPANY_ID, "https://ph.example/webhook")

        assert result.success is False

    @mock.patch(WHOP_SESSION_PATCH)
    def test_transport_failure_is_reported_not_raised(self, MockSession):
        MockSession.return_value.post.side_effect = Exception("boom")
        assert create_webhook("key", COMPANY_ID, "https://ph.example/webhook").success is False


def _webhook_list_page(items: list[dict[str, Any]], end_cursor: str | None, has_next_page: bool) -> mock.MagicMock:
    return _json_response(200, {"data": items, "page_info": {"end_cursor": end_cursor, "has_next_page": has_next_page}})


class TestWebhookManagement:
    @mock.patch(WHOP_SESSION_PATCH)
    def test_lookup_pages_through_every_webhook(self, MockSession):
        session = MockSession.return_value
        session.get.side_effect = [
            _webhook_list_page([{"id": "hook_1", "url": "https://other.example"}], "cursor-1", True),
            _webhook_list_page(
                [
                    {
                        "id": "hook_2",
                        "url": "https://ph.example/webhook",
                        "events": ["payment.succeeded"],
                        "enabled": True,
                    }
                ],
                None,
                False,
            ),
        ]

        info = get_external_webhook_info("key", COMPANY_ID, "https://ph.example/webhook")

        assert info.exists is True
        assert info.enabled_events == ["payment.succeeded"]
        assert info.status == "enabled"
        assert "after=cursor-1" in session.get.call_args_list[1].args[0]

    @mock.patch(WHOP_SESSION_PATCH)
    def test_lookup_reports_absence(self, MockSession):
        MockSession.return_value.get.return_value = _webhook_list_page([], None, False)

        assert get_external_webhook_info("key", COMPANY_ID, "https://ph.example/webhook").exists is False

    @mock.patch(WHOP_SESSION_PATCH)
    def test_sync_merges_missing_events_and_keeps_existing_ones(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _webhook_list_page(
            [{"id": "hook_1", "url": "https://ph.example/webhook", "events": ["payment.created", "custom.event"]}],
            None,
            False,
        )

        result = sync_webhook_events("key", COMPANY_ID, "https://ph.example/webhook", ["payment.succeeded"])

        assert result.success is True
        assert session.patch.call_args.kwargs["json"] == {
            "events": ["custom.event", "payment.created", "payment.succeeded"]
        }

    @mock.patch(WHOP_SESSION_PATCH)
    def test_sync_skips_the_write_when_events_already_match(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _webhook_list_page(
            [{"id": "hook_1", "url": "https://ph.example/webhook", "events": ["payment.succeeded"]}], None, False
        )

        assert sync_webhook_events("key", COMPANY_ID, "https://ph.example/webhook", ["payment.succeeded"]).success
        session.patch.assert_not_called()

    @mock.patch(WHOP_SESSION_PATCH)
    def test_delete_removes_only_matching_webhooks(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _webhook_list_page(
            [
                {"id": "hook_1", "url": "https://other.example"},
                {"id": "hook_2", "url": "https://ph.example/webhook"},
            ],
            None,
            False,
        )
        session.delete.return_value = mock.MagicMock(status_code=204)

        result = delete_webhook("key", COMPANY_ID, "https://ph.example/webhook")

        assert result.success is True
        assert session.delete.call_args.args[0].endswith("/webhooks/hook_2")

    @mock.patch(WHOP_SESSION_PATCH)
    def test_delete_surfaces_a_rejected_removal(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _webhook_list_page(
            [{"id": "hook_2", "url": "https://ph.example/webhook"}], None, False
        )
        session.delete.return_value = mock.MagicMock(status_code=403)

        assert delete_webhook("key", COMPANY_ID, "https://ph.example/webhook").success is False
