from typing import Any, Optional, cast

import pytest
from unittest.mock import patch

import orjson
from parameterized import parameterized
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
    PADDLE_BASE_URL,
    _base_url,
    _get_paddle_session,
    _make_webhook_table_transformer,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    update_webhook_events,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.settings import PADDLE_WEBHOOK_EVENTS
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.source import PaddleSource

MOCK_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle.requests.Session.request"

LIVE_HOST = "https://api.paddle.com"
SANDBOX_HOST = "https://sandbox-api.paddle.com"
WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/some-hog-fn-id"


class MockResponse:
    def __init__(self, json_data: Any, status_code: int = 200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self) -> Any:
        return self.json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"HTTP Error {self.status_code}", response=cast(Any, self))


def _settings_list_response(items: list[dict[str, Any]], next_url: Optional[str] = None) -> MockResponse:
    return MockResponse({"data": items, "meta": {"pagination": {"next": next_url}}})


def _setting(
    setting_id: str = "ntfset_1",
    destination: str = WEBHOOK_URL,
    active: bool = True,
    secret: Optional[str] = "pdl_ntfset_secret",
    events: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "id": setting_id,
        "description": "PostHog data warehouse webhook",
        "destination": destination,
        "active": active,
        "endpoint_secret_key": secret,
        "subscribed_events": [{"name": name} for name in (events if events is not None else PADDLE_WEBHOOK_EVENTS)],
    }


def _envelope(
    entity: dict[str, Any],
    event_type: str = "transaction.updated",
    occurred_at: str = "2024-01-01T00:00:00.000Z",
) -> dict[str, Any]:
    return {
        "event_id": f"evt_{entity.get('id', 'x')}_{occurred_at}",
        "event_type": event_type,
        "occurred_at": occurred_at,
        "notification_id": "ntf_1",
        "data": entity,
    }


def _transform(table: Any, required_field: Optional[str] = None) -> Any:
    return _make_webhook_table_transformer(required_field)(table)


class TestPaddleSession:
    def test_session_retries_rate_limits(self):
        session = _get_paddle_session("pdl_test_key")
        retry = cast(HTTPAdapter, session.get_adapter(PADDLE_BASE_URL)).max_retries

        # A transient 429 must back off and retry rather than failing the whole sync.
        assert retry.total is not None and retry.total > 0
        assert retry.is_retry("GET", 429) is True
        assert retry.respect_retry_after_header is True
        # Persistent failures still surface via response.raise_for_status(), not MaxRetryError.
        assert retry.raise_on_status is False

    def test_auth_failures_are_not_retried(self):
        session = _get_paddle_session("pdl_test_key")
        retry = cast(HTTPAdapter, session.get_adapter(PADDLE_BASE_URL)).max_retries

        # 401/403/400 are credential/config problems handled by get_non_retryable_errors;
        # retrying them would only delay surfacing the error to the user.
        assert retry.is_retry("GET", 401) is False
        assert retry.is_retry("GET", 403) is False
        assert retry.is_retry("GET", 400) is False


class TestBaseUrl:
    @parameterized.expand(
        [
            ("live", "live", LIVE_HOST),
            ("sandbox", "sandbox", SANDBOX_HOST),
            # Sources created before the environment field existed have no value stored —
            # they must keep hitting the live API.
            ("missing", None, LIVE_HOST),
            ("empty", "", LIVE_HOST),
            ("unknown", "junk", LIVE_HOST),
        ]
    )
    def test_base_url(self, _name, environment, expected):
        assert _base_url(environment) == expected


class TestWebhookTableTransformer:
    def test_unwraps_envelope_to_entity_rows(self):
        table = table_from_py_list(
            [_envelope({"id": "txn_1", "status": "completed", "created_at": "2024-01-01T00:00:00Z"})]
        )
        result = _transform(table)

        assert result.num_rows == 1
        row = result.to_pylist()[0]
        # Rows must be entity-shaped and carry the merge key.
        assert row["id"] == "txn_1"
        assert row["created_at"] == "2024-01-01T00:00:00Z"
        assert row["status"] == "completed"
        assert "event_type" not in result.column_names

    def test_dedupes_to_latest_by_parsed_occurred_at(self):
        # "…48.123Z" sorts before "…48.12Z" lexicographically but is the later instant —
        # a string comparison would keep the stale row.
        stale = _envelope({"id": "txn_1", "status": "stale"}, occurred_at="2024-01-01T00:00:48.12Z")
        fresh = _envelope({"id": "txn_1", "status": "fresh"}, occurred_at="2024-01-01T00:00:48.123Z")

        for envelopes in ([stale, fresh], [fresh, stale]):
            result = _transform(table_from_py_list(envelopes))
            assert result.num_rows == 1
            assert result.to_pylist()[0]["status"] == "fresh"

    def test_tie_keeps_last_seen_event(self):
        first = _envelope({"id": "txn_1", "status": "first"}, occurred_at="2024-01-01T00:00:00Z")
        second = _envelope({"id": "txn_1", "status": "second"}, occurred_at="2024-01-01T00:00:00Z")

        result = _transform(table_from_py_list([first, second]))

        assert result.num_rows == 1
        # S3 files are read oldest-first, so on equal timestamps the later arrival wins.
        assert result.to_pylist()[0]["status"] == "second"

    def test_data_as_json_string(self):
        envelope = _envelope({"id": "txn_1", "status": "completed"})
        envelope["data"] = orjson.dumps(envelope["data"]).decode()

        result = _transform(table_from_py_list([envelope]))

        assert result.num_rows == 1
        assert result.to_pylist()[0]["id"] == "txn_1"

    def test_skips_null_and_malformed_data_and_missing_id_rows(self):
        # Malformed rows must be skipped, not raised on: a crash leaves the buffered S3
        # file in place and every retry re-crashes on it.
        envelopes = [
            _envelope({"id": "txn_1"}),
            {**_envelope({"id": "ignored"}), "data": None},
            {**_envelope({"id": "ignored"}), "data": orjson.dumps([{"id": "txn_in_list"}]).decode()},
            {**_envelope({"id": "ignored"}), "data": "not json at all"},
            _envelope({"status": "no id"}),
        ]

        result = _transform(table_from_py_list(envelopes))

        rows = result.to_pylist()
        assert [row["id"] for row in rows] == ["txn_1"]

    def test_transaction_drafts_without_billed_at_are_dropped(self):
        # The webhook path mirrors the pull cursor (billed_at[GT]): draft transactions have no
        # billed_at and must not enter, keeping billed_at (the partition key) non-null.
        envelopes = [
            _envelope({"id": "txn_draft", "status": "ready"}),
            _envelope({"id": "txn_billed", "status": "billed", "billed_at": "2024-01-01T00:00:00Z"}),
        ]

        result = _transform(table_from_py_list(envelopes), "billed_at")

        assert [row["id"] for row in result.to_pylist()] == ["txn_billed"]

    def test_no_required_field_keeps_rows_without_it(self):
        # Endpoints with no incremental field (e.g. customers) don't filter on a cursor.
        result = _transform(
            table_from_py_list([_envelope({"id": "ctm_01h8xq9j5m2k3n4p5q6r7s8t9a"}, event_type="customer.updated")])
        )

        assert [row["id"] for row in result.to_pylist()] == ["ctm_01h8xq9j5m2k3n4p5q6r7s8t9a"]

    def test_distinct_ids_all_kept(self):
        envelopes = [_envelope({"id": f"txn_{i}"}) for i in range(3)]

        result = _transform(table_from_py_list(envelopes))

        assert sorted(row["id"] for row in result.to_pylist()) == ["txn_0", "txn_1", "txn_2"]

    def test_missing_data_column_returns_empty(self):
        result = _transform(table_from_py_list([{"event_type": "transaction.updated"}]))
        assert result.num_rows == 0


class TestCreateWebhook:
    @patch(MOCK_PATH)
    def test_creates_destination_and_returns_secret(self, mock_request):
        mock_request.side_effect = [
            _settings_list_response([]),
            MockResponse({"data": _setting(secret="pdl_ntfset_new")}),
        ]

        result = create_webhook("key", "live", WEBHOOK_URL)

        assert result.success is True
        # The secret must flow back so signature verification configures itself.
        assert result.extra_inputs == {"signing_secret": "pdl_ntfset_new"}
        assert result.pending_inputs == []

        method, url = mock_request.call_args_list[1][0]
        body = mock_request.call_args_list[1][1]["json"]
        assert method == "POST"
        assert url == f"{LIVE_HOST}/notification-settings"
        assert body["destination"] == WEBHOOK_URL
        assert body["type"] == "url"
        assert body["active"] is True
        assert body["subscribed_events"] == PADDLE_WEBHOOK_EVENTS

    @patch(MOCK_PATH)
    def test_sandbox_environment_hits_sandbox_host(self, mock_request):
        mock_request.side_effect = [
            _settings_list_response([]),
            MockResponse({"data": _setting()}),
        ]

        create_webhook("key", "sandbox", WEBHOOK_URL)

        for call in mock_request.call_args_list:
            assert call[0][1].startswith(SANDBOX_HOST)

    @patch(MOCK_PATH)
    def test_existing_destination_reused_without_duplicate_post(self, mock_request):
        mock_request.side_effect = [_settings_list_response([_setting(secret="pdl_ntfset_existing")])]

        result = create_webhook("key", "live", WEBHOOK_URL)

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "pdl_ntfset_existing"}
        # Only the list call — re-creating would register duplicate destinations in Paddle.
        assert mock_request.call_count == 1

    @patch(MOCK_PATH)
    def test_existing_inactive_destination_is_reactivated(self, mock_request):
        mock_request.side_effect = [
            _settings_list_response([_setting(setting_id="ntfset_9", active=False)]),
            MockResponse({"data": _setting(setting_id="ntfset_9", active=True)}),
        ]

        result = create_webhook("key", "live", WEBHOOK_URL)

        assert result.success is True
        method, url = mock_request.call_args_list[1][0]
        assert method == "PATCH"
        assert url == f"{LIVE_HOST}/notification-settings/ntfset_9"
        assert mock_request.call_args_list[1][1]["json"] == {"active": True}

    @patch(MOCK_PATH)
    def test_existing_destination_without_secret_reports_pending_input(self, mock_request):
        mock_request.side_effect = [_settings_list_response([_setting(secret=None)])]

        result = create_webhook("key", "live", WEBHOOK_URL)

        assert result.success is True
        assert result.extra_inputs == {}
        assert result.pending_inputs == ["signing_secret"]

    @parameterized.expand(
        [
            ("permission_denied", 403, "write permission"),
            ("bad_key", 401, "rejected the API key"),
        ]
    )
    @patch(MOCK_PATH)
    def test_http_errors_return_friendly_result(self, _name, status_code, expected_fragment, mock_request):
        mock_request.return_value = MockResponse({"error": {"code": "denied"}}, status_code=status_code)

        result = create_webhook("key", "live", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and expected_fragment in result.error

    @patch(MOCK_PATH)
    def test_error_surfaces_paddle_detail_and_code(self, mock_request):
        # A generic "Paddle API error (400)" hides why the call failed (e.g. account at its
        # notification-settings cap) — the structured detail must reach the user.
        mock_request.return_value = MockResponse(
            {
                "error": {
                    "code": "notification_maximum_active_settings_reached",
                    "detail": "Maximum number of notification settings reached",
                }
            },
            status_code=400,
        )

        result = create_webhook("key", "live", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None
        assert "Maximum number of notification settings reached" in result.error
        assert "notification_maximum_active_settings_reached" in result.error

    @patch(MOCK_PATH)
    def test_error_surfaces_invalid_field_messages(self, mock_request):
        # Paddle returns per-field validation errors under `errors`; a bad event name must
        # tell the user which value was rejected, not just "400".
        mock_request.return_value = MockResponse(
            {
                "error": {
                    "code": "invalid_field",
                    "detail": "Invalid request",
                    "errors": [{"field": "subscribed_events", "message": "transaction.bogus is not a valid event"}],
                }
            },
            status_code=400,
        )

        result = create_webhook("key", "live", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None
        assert "subscribed_events: transaction.bogus is not a valid event" in result.error

    @patch(MOCK_PATH)
    def test_non_dict_error_body_does_not_raise(self, mock_request):
        # An intermediary returning {"error": "<string>"} (not Paddle's object shape) must not
        # crash the never-raise contract via AttributeError inside the except handler.
        mock_request.return_value = MockResponse({"error": "gateway exploded"}, status_code=400)

        result = create_webhook("key", "live", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "400" in result.error


class TestUpdateWebhookEvents:
    @patch(MOCK_PATH)
    def test_merges_missing_events_on_drift(self, mock_request):
        mock_request.side_effect = [
            _settings_list_response(
                [_setting(setting_id="ntfset_1", events=["transaction.completed", "custom.event"])]
            ),
            MockResponse({"data": _setting()}),
        ]

        result = update_webhook_events("key", "live", WEBHOOK_URL, ["transaction.completed", "transaction.updated"])

        assert result.success is True
        method, url = mock_request.call_args_list[1][0]
        assert method == "PATCH"
        assert url == f"{LIVE_HOST}/notification-settings/ntfset_1"
        # Union, never replacement — a user-added subscription must survive reconciliation.
        assert mock_request.call_args_list[1][1]["json"] == {
            "subscribed_events": ["custom.event", "transaction.completed", "transaction.updated"]
        }

    @patch(MOCK_PATH)
    def test_no_write_when_already_subscribed(self, mock_request):
        mock_request.side_effect = [_settings_list_response([_setting(events=PADDLE_WEBHOOK_EVENTS)])]

        result = update_webhook_events("key", "live", WEBHOOK_URL, list(PADDLE_WEBHOOK_EVENTS))

        assert result.success is True
        # Reconcile runs on every schema enable; drift-free must not PATCH.
        assert mock_request.call_count == 1

    @patch(MOCK_PATH)
    def test_missing_destination_is_success(self, mock_request):
        mock_request.side_effect = [_settings_list_response([])]

        result = update_webhook_events("key", "live", WEBHOOK_URL, ["transaction.updated"])

        assert result.success is True
        assert mock_request.call_count == 1


class TestDeleteWebhook:
    @patch(MOCK_PATH)
    def test_deletes_matching_destination(self, mock_request):
        mock_request.side_effect = [
            _settings_list_response([_setting(setting_id="ntfset_7")]),
            MockResponse({}, status_code=204),
        ]

        result = delete_webhook("key", "live", WEBHOOK_URL)

        assert result.success is True
        method, url = mock_request.call_args_list[1][0]
        assert method == "DELETE"
        assert url == f"{LIVE_HOST}/notification-settings/ntfset_7"

    @patch(MOCK_PATH)
    def test_absent_destination_is_success(self, mock_request):
        mock_request.side_effect = [_settings_list_response([])]

        result = delete_webhook("key", "live", WEBHOOK_URL)

        # Source deletion must not fail when the user already removed the destination.
        assert result.success is True

    @patch(MOCK_PATH)
    def test_delete_race_404_is_success(self, mock_request):
        mock_request.side_effect = [
            _settings_list_response([_setting(setting_id="ntfset_7")]),
            MockResponse({"error": "not found"}, status_code=404),
        ]

        result = delete_webhook("key", "live", WEBHOOK_URL)

        assert result.success is True


class TestGetExternalWebhookInfo:
    @patch(MOCK_PATH)
    def test_maps_destination_fields(self, mock_request):
        mock_request.side_effect = [_settings_list_response([_setting(active=False, events=["transaction.completed"])])]

        info = get_external_webhook_info("key", "live", WEBHOOK_URL)

        assert info.exists is True
        assert info.url == WEBHOOK_URL
        assert info.enabled_events == ["transaction.completed"]
        assert info.status == "disabled"

    @patch(MOCK_PATH)
    def test_absent_destination(self, mock_request):
        mock_request.side_effect = [_settings_list_response([])]

        info = get_external_webhook_info("key", "live", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is None

    @patch(MOCK_PATH)
    def test_pagination_combines_pages_and_terminates_on_repeating_next(self, mock_request):
        # Paddle returns a `next` cursor even on the last page, so termination relies on the
        # seen-urls guard. A second page whose `next` points back at an already-fetched URL must
        # stop the walk (not loop forever against Paddle) while still combining both pages.
        next_url = f"{LIVE_HOST}/notification-settings?after=cursor2"
        mock_request.side_effect = [
            _settings_list_response([_setting(setting_id="ntfset_other", destination="https://other")], next_url),
            _settings_list_response([_setting(setting_id="ntfset_match")], next_url),
        ]

        info = get_external_webhook_info("key", "live", WEBHOOK_URL)

        assert info.exists is True
        assert mock_request.call_count == 2


class TestWebhookClientErrorHandling:
    @parameterized.expand(
        [
            (
                "update_webhook_events",
                lambda: update_webhook_events("key", "live", WEBHOOK_URL, ["transaction.updated"]),
                [
                    _settings_list_response([_setting(events=["transaction.completed"])]),
                    MockResponse({"error": {"code": "forbidden", "detail": "needs write permission"}}, status_code=403),
                ],
            ),
            (
                "delete_webhook",
                lambda: delete_webhook("key", "live", WEBHOOK_URL),
                [
                    _settings_list_response([_setting()]),
                    MockResponse({"error": {"code": "forbidden", "detail": "needs write permission"}}, status_code=403),
                ],
            ),
        ]
    )
    @patch(MOCK_PATH)
    def test_returns_friendly_result_on_http_error(self, _name, invoke, side_effect, mock_request):
        # update/delete must honor the same never-raise contract as create: an HTTP error on the
        # mutating call returns a failed result surfacing Paddle's detail, not an exception.
        mock_request.side_effect = side_effect

        result = invoke()

        assert result.success is False
        assert result.error is not None and "needs write permission" in result.error


class TestPaddleNonRetryableErrors:
    @pytest.mark.parametrize(
        "observed_error",
        [
            # A 404 on a list endpoint we know exists means the resource isn't reachable for this
            # account (Billing not enabled, or a wrong-environment key) — retrying can't fix it.
            "404 Client Error: Not Found for url: https://api.paddle.com/subscriptions?per_page=200&order_by=id%5BASC%5D",
            "400 Client Error: Bad Request for url: https://api.paddle.com/transactions?per_page=200",
            "401 Client Error: Unauthorized for url: https://api.paddle.com/customers",
            "403 Client Error: Forbidden for url: https://api.paddle.com/products",
        ],
    )
    def test_non_retryable_errors_match_client_failures(self, observed_error):
        non_retryable_errors = PaddleSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            # Transient/infra errors must stay retryable.
            "HTTPSConnectionPool(host='api.paddle.com', port=443): Read timed out.",
            "500 Server Error: Internal Server Error for url: https://api.paddle.com/subscriptions",
            "Connection reset by peer",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = PaddleSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
