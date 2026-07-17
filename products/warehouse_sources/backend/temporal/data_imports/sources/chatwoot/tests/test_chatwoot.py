import json
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot import (
    ChatwootResumeConfig,
    _normalize_account_id,
    chatwoot_source,
    create_webhook,
    delete_webhook,
    get_rows,
    make_webhook_table_transformer,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.settings import (
    CHATWOOT_ENDPOINTS,
    ENDPOINTS,
    MESSAGES_PAGE_SIZE,
)

TEAM_ID = 1


def _make_manager(resume_state: ChatwootResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _resp(payload: Any, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.is_redirect = False
    resp.is_permanent_redirect = False
    resp.iter_content.return_value = [json.dumps(payload).encode()]
    resp.json.return_value = payload
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=resp)
    return resp


def _conversations_page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"data": {"meta": {}, "payload": items}}


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "host, expected",
        [
            (None, "https://app.chatwoot.com"),
            ("", "https://app.chatwoot.com"),
            ("chatwoot.example.com", "https://chatwoot.example.com"),
            ("https://chatwoot.example.com/", "https://chatwoot.example.com"),
            ("https://chatwoot.example.com/api/v1", "https://chatwoot.example.com"),
            ("http://chatwoot.example.com", "http://chatwoot.example.com"),
        ],
    )
    def test_normalize_host(self, host, expected):
        assert normalize_host(host) == expected


class TestNormalizeAccountId:
    @pytest.mark.parametrize("account_id", ["1", 42, " 7 "])
    def test_accepts_numeric(self, account_id):
        assert _normalize_account_id(account_id).isdigit()

    @pytest.mark.parametrize("account_id", ["", None, "1/../2", "abc", "1?x=1"])
    def test_rejects_non_numeric(self, account_id):
        with pytest.raises(ValueError):
            _normalize_account_id(account_id)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [(200, True), (401, False), (404, False), (500, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_status_mapping(self, mock_session, status_code, expected_valid):
        mock_session.return_value.get.return_value = _resp([], status=status_code)

        is_valid, _ = validate_credentials(None, "1", "token", TEAM_ID)

        assert is_valid is expected_valid

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_connection_error_is_reported_not_raised(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        is_valid, message = validate_credentials(None, "1", "token", TEAM_ID)

        assert is_valid is False
        assert message is not None and "Could not connect" in message

    def test_plain_http_host_is_rejected(self):
        is_valid, message = validate_credentials("http://chatwoot.internal", "1", "token", TEAM_ID)

        assert is_valid is False
        assert message is not None and "HTTPS" in message

    def test_non_numeric_account_id_is_rejected_without_a_request(self):
        is_valid, message = validate_credentials(None, "not-a-number", "token", TEAM_ID)

        assert is_valid is False
        assert message is not None and "number" in message


class TestGetRowsPaged:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_conversations_walks_pages_with_status_all_until_empty(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp(_conversations_page([{"id": 1}, {"id": 2}])),
            _resp(_conversations_page([{"id": 3}])),
            _resp(_conversations_page([])),
        ]
        manager = _make_manager()

        batches = list(get_rows(None, "1", "token", "conversations", TEAM_ID, mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [1, 2, 3]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        # status defaults to "open" server-side — dropping status=all would silently sync a subset.
        assert all("status=all" in url and "sort_by=created_at_asc" in url for url in urls)
        assert ["page=1" in urls[0], "page=2" in urls[1], "page=3" in urls[2]] == [True, True, True]
        # State is saved after each yielded page, pointing at the next page; the empty final
        # page yields nothing and saves nothing.
        assert [call.args[0].page for call in manager.save_state.call_args_list] == [2, 3]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp({"meta": {}, "payload": [{"id": 9}]}),
            _resp({"meta": {}, "payload": []}),
        ]
        manager = _make_manager(ChatwootResumeConfig(page=5))

        list(get_rows(None, "1", "token", "contacts", TEAM_ID, mock.MagicMock(), manager))

        assert "page=5" in mock_session.return_value.get.call_args_list[0].args[0]

    @pytest.mark.parametrize(
        "endpoint, payload, expected_ids",
        [
            ("agents", [{"id": 1}, {"id": 2}], [1, 2]),
            ("teams", [{"id": 3}], [3]),
            ("custom_attribute_definitions", [{"id": 4}], [4]),
            ("labels", {"payload": [{"id": 5}]}, [5]),
            ("inboxes", {"payload": [{"id": 6}]}, [6]),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_single_endpoints_yield_once_without_pagination(self, mock_session, endpoint, payload, expected_ids):
        mock_session.return_value.get.return_value = _resp(payload)
        manager = _make_manager()

        batches = list(get_rows(None, "1", "token", endpoint, TEAM_ID, mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == expected_ids
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_plain_http_host_raises(self):
        with pytest.raises(Exception, match="HTTPS"):
            list(
                get_rows("http://chatwoot.internal", "1", "token", "agents", TEAM_ID, mock.MagicMock(), _make_manager())
            )


class TestGetRowsMessages:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_fans_out_over_conversations_with_after_cursor(self, mock_session):
        full_page = [{"id": 100 + i} for i in range(MESSAGES_PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _resp(_conversations_page([{"id": 1}, {"id": 2}])),
            _resp(_conversations_page([])),
            # Conversation 1: one full page, then a short page ends it.
            _resp({"meta": {}, "payload": full_page}),
            _resp({"meta": {}, "payload": [{"id": 300}]}),
            # Conversation 2: single short page.
            _resp({"meta": {}, "payload": [{"id": 400}]}),
        ]
        manager = _make_manager()

        batches = list(get_rows(None, "1", "token", "messages", TEAM_ID, mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [*[m["id"] for m in full_page], 300, 400]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[2].endswith("/conversations/1/messages?after=0")
        assert urls[3].endswith(f"/conversations/1/messages?after={full_page[-1]['id']}")
        assert urls[4].endswith("/conversations/2/messages?after=0")
        # Cursor state saved after each yielded page; bookmark advanced to the next conversation.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert (saved[0].conversation_id, saved[0].after) == (1, full_page[-1]["id"])
        assert any(state.conversation_id == 2 and state.after == 0 for state in saved)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_deleted_conversation_404_is_skipped(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp(_conversations_page([{"id": 1}, {"id": 2}])),
            _resp(_conversations_page([])),
            _resp({"error": "Resource could not be found"}, status=404),
            _resp({"meta": {}, "payload": [{"id": 400}]}),
        ]
        manager = _make_manager()

        batches = list(get_rows(None, "1", "token", "messages", TEAM_ID, mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [400]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.MAX_MESSAGE_PAGES_PER_SYNC",
        2,
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_message_walk_stops_at_the_aggregate_page_cap(self, mock_session):
        # A hostile server can keep returning full, advancing pages; the per-conversation cap alone
        # would still let conversation count multiply requests without bound, so the walk must stop
        # once the aggregate page budget is spent rather than fanning out further.
        page_one = [{"id": 100 + i} for i in range(MESSAGES_PAGE_SIZE)]
        page_two = [{"id": 200 + i} for i in range(MESSAGES_PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _resp(_conversations_page([{"id": 1}, {"id": 2}])),
            _resp(_conversations_page([])),
            _resp({"meta": {}, "payload": page_one}),
            _resp({"meta": {}, "payload": page_two}),
            # A third message page would be fetched without the aggregate cap; it must not be.
            _resp({"meta": {}, "payload": [{"id": 999}]}),
        ]
        manager = _make_manager()

        batches = list(get_rows(None, "1", "token", "messages", TEAM_ID, mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [
            *[m["id"] for m in page_one],
            *[m["id"] for m in page_two],
        ]
        message_urls = [
            call.args[0] for call in mock_session.return_value.get.call_args_list if "/messages" in call.args[0]
        ]
        assert len(message_urls) == 2
        assert not any("/conversations/2/messages" in url for url in message_urls)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_resumes_from_bookmarked_conversation_and_cursor(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp(_conversations_page([{"id": 1}, {"id": 2}])),
            _resp(_conversations_page([])),
            _resp({"meta": {}, "payload": [{"id": 25}]}),
        ]
        manager = _make_manager(ChatwootResumeConfig(conversation_id=2, after=20))

        batches = list(get_rows(None, "1", "token", "messages", TEAM_ID, mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [25]
        message_urls = [
            call.args[0] for call in mock_session.return_value.get.call_args_list if "/messages" in call.args[0]
        ]
        assert message_urls == ["https://app.chatwoot.com/api/v1/accounts/1/conversations/2/messages?after=20"]


class TestWebhookTableTransformer:
    def test_message_events_are_normalized_to_the_rest_shape(self):
        transform = make_webhook_table_transformer("messages")
        table = table_from_py_list(
            [
                {
                    "event": "message_created",
                    "id": 10,
                    "content": "hi",
                    "message_type": "incoming",
                    "created_at": "2026-01-02T03:04:05.000Z",
                    "conversation": {"id": 7, "status": "open"},
                    "account": {"id": 1, "name": "acme"},
                    "inbox": {"id": 2, "name": "support"},
                },
                {
                    "event": "message_updated",
                    "id": 10,
                    "content": "hi (edited)",
                    "message_type": "incoming",
                    "created_at": "2026-01-02T03:04:05.000Z",
                    "conversation": {"id": 7, "status": "open"},
                    "account": {"id": 1, "name": "acme"},
                    "inbox": {"id": 2, "name": "support"},
                },
            ]
        )

        rows = transform(table).to_pylist()

        # Deduped within the batch, keeping the latest event for the id.
        assert len(rows) == 1
        row = rows[0]
        assert row["content"] == "hi (edited)"
        assert row["conversation_id"] == 7
        # REST returns message_type as an int and created_at as a unix int; webhook rows must
        # merge into the same column types.
        assert row["message_type"] == 0
        assert row["created_at"] == 1767323045
        assert "event" not in row and "account" not in row and "conversation" not in row and "inbox" not in row

    def test_conversation_events_drop_event_context_keys(self):
        transform = make_webhook_table_transformer("conversations")
        table = table_from_py_list(
            [
                {
                    "event": "conversation_status_changed",
                    "id": 5,
                    "status": "resolved",
                    "created_at": 1767323045,
                    "account": {"id": 1, "name": "acme"},
                    "changed_attributes": [{"status": {"current_value": "resolved", "previous_value": "open"}}],
                }
            ]
        )

        rows = transform(table).to_pylist()

        assert rows == [{"id": 5, "status": "resolved", "created_at": 1767323045}]

    def test_rows_without_an_id_are_dropped(self):
        transform = make_webhook_table_transformer("conversations")
        table = table_from_py_list([{"event": "conversation_created", "status": "open", "id": None}])

        assert transform(table).num_rows == 0


class TestWebhookManagement:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_create_webhook_returns_signing_secret_as_extra_input(self, mock_session):
        mock_session.return_value.post.return_value = _resp(
            {"payload": {"webhook": {"id": 3, "url": "https://ph/webhook", "secret": "s3cret"}}}
        )

        result = create_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "s3cret"}
        assert result.pending_inputs == []
        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["webhook"]["url"] == "https://ph/webhook"
        assert set(body["webhook"]["subscriptions"]) == {
            "conversation_created",
            "conversation_updated",
            "conversation_status_changed",
            "message_created",
            "message_updated",
        }

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_create_webhook_without_secret_marks_signing_secret_pending(self, mock_session):
        # Older self-hosted Chatwoot versions have no per-webhook secret.
        mock_session.return_value.post.return_value = _resp(
            {"payload": {"webhook": {"id": 3, "url": "https://ph/webhook"}}}
        )

        result = create_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]

    @pytest.mark.parametrize("status", [401, 403])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_create_webhook_permission_error_is_actionable(self, mock_session, status):
        mock_session.return_value.post.return_value = _resp({"error": "nope"}, status=status)

        result = create_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is False
        assert result.error is not None and "administrator" in result.error

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_create_webhook_reconciles_existing_webhook_on_422(self, mock_session):
        # Webhook URLs are unique per account: a partial earlier setup 422s on re-create.
        mock_session.return_value.post.return_value = _resp({"message": "URL has already been taken"}, status=422)
        mock_session.return_value.get.return_value = _resp(
            {"payload": {"webhooks": [{"id": 9, "url": "https://ph/webhook", "subscriptions": ["message_created"]}]}}
        )
        mock_session.return_value.patch.return_value = _resp(
            {"payload": {"webhook": {"id": 9, "url": "https://ph/webhook", "secret": "s3cret"}}}
        )

        result = create_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "s3cret"}
        assert "/webhooks/9" in mock_session.return_value.patch.call_args.args[0]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.make_tracked_session"
    )
    def test_delete_webhook_is_a_noop_success_when_absent(self, mock_session):
        mock_session.return_value.get.return_value = _resp({"payload": {"webhooks": []}})

        result = delete_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is True
        mock_session.return_value.delete.assert_not_called()


class TestChatwootSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CHATWOOT_ENDPOINTS[endpoint]
        response = chatwoot_source(
            None, "1", "token", endpoint, TEAM_ID, mock.MagicMock(), _make_manager(), webhook_source_manager=None
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(CHATWOOT_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"

    def test_webhook_enabled_schema_reads_from_webhook_manager(self):
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        response = chatwoot_source(
            None, "1", "token", "conversations", TEAM_ID, mock.MagicMock(), _make_manager(), webhook_manager
        )
        response.items()

        webhook_manager.get_items.assert_called_once()

    def test_webhook_manager_not_consulted_for_non_webhook_schema(self):
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        chatwoot_source(None, "1", "token", "agents", TEAM_ID, mock.MagicMock(), _make_manager(), webhook_manager)

        webhook_manager.webhook_enabled.assert_not_called()
