import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot import (
    REPORTING_EVENTS_UNAVAILABLE_ERROR,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.source import ChatwootSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chatwoot import (
    ChatwootSourceConfig,
)

TEAM_ID = 1


def _driver() -> SourceDriver:
    return SourceDriver(ChatwootSource(), ChatwootSourceConfig(account_id="1", api_access_token="token"))


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
    @pytest.mark.parametrize("account_id", ["", None, "1/../2", "abc", "1?x=1"])
    def test_rejects_non_numeric(self, account_id):
        with pytest.raises(ValueError):
            _normalize_account_id(account_id)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [(404, False)],
    )
    def test_status_mapping(self, status_code, expected_valid):
        with scripted_network(always(ScriptedResponse(status=status_code, json=[]))) as network:
            is_valid, _ = validate_credentials(None, "1", "token", TEAM_ID)

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/api/v1/accounts/1/agents"}

    def test_connection_error_is_reported_not_raised(self):
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials(None, "1", "token", TEAM_ID)

        assert is_valid is False
        assert message is not None and "Could not connect" in message
        assert {request.path for request in network.requests_log} == {"/api/v1/accounts/1/agents"}

    def test_plain_http_host_is_rejected(self):
        is_valid, message = validate_credentials("http://chatwoot.internal", "1", "token", TEAM_ID)

        assert is_valid is False
        assert message is not None and "HTTPS" in message

    def test_non_numeric_account_id_is_rejected_without_a_request(self):
        is_valid, message = validate_credentials(None, "not-a-number", "token", TEAM_ID)

        assert is_valid is False
        assert message is not None and "number" in message

    @pytest.mark.parametrize(
        "host",
        [
            "https://169.254.169.254\\@attacker.example",
            "https://user@attacker.example",
            "https://169.254.169.254%5c@attacker.example",
            "https://169.254.169.254%40attacker.example",
        ],
    )
    def test_authority_ambiguous_host_is_rejected_without_a_request(self, host):
        # urlparse and the HTTP client disagree on where the host ends, so these must be rejected
        # before any request — otherwise the host allowlist is an SSRF bypass.
        with scripted_network([]) as network:
            is_valid, message = validate_credentials(host, "1", "token", TEAM_ID)

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []


class TestGetRowsPaged:
    def test_resumes_from_saved_page(self):
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json={"meta": {}, "payload": [{"id": 9}]}),
                ScriptedResponse(json={"meta": {}, "payload": []}),
            ],
            resume_state=ChatwootResumeConfig(page=5),
        )

        assert result.params("page") == ["5", "6"]
        assert [row["id"] for row in result.rows] == [9]

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
    def test_single_endpoints_yield_once_without_pagination(self, endpoint, payload, expected_ids):
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])

        assert [item["id"] for item in result.rows] == expected_ids
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_plain_http_host_raises(self):
        driver = SourceDriver(
            ChatwootSource(),
            ChatwootSourceConfig(account_id="1", api_access_token="token", host="http://chatwoot.internal"),
        )
        result = driver.run("agents", [])

        assert isinstance(result.raised, Exception)
        assert "HTTPS" in str(result.raised)
        assert result.requests == []

    def test_authority_ambiguous_host_raises(self):
        driver = SourceDriver(
            ChatwootSource(),
            ChatwootSourceConfig(
                account_id="1", api_access_token="token", host="https://169.254.169.254\\@attacker.example"
            ),
        )
        result = driver.run("agents", [])

        assert isinstance(result.raised, Exception)
        assert "not allowed" in str(result.raised)
        assert result.requests == []


class TestGetRowsMessages:
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


class TestGetRowsMemberFanout:
    def test_deleted_parent_404_is_skipped(self):
        result = _driver().run(
            "team_members",
            [
                ScriptedResponse(json=[{"id": 10}, {"id": 11}]),
                ScriptedResponse(status=404, json={"error": "Resource could not be found"}),
                ScriptedResponse(json=[{"id": 2}]),
            ],
        )

        assert [row["id"] for row in result.rows] == [2]
        assert result.paths == [
            "/api/v1/accounts/1/teams",
            "/api/v1/accounts/1/teams/10/team_members",
            "/api/v1/accounts/1/teams/11/team_members",
        ]

    @pytest.mark.parametrize(
        "bookmarked_parent_id, expected_team_ids",
        # A bookmark for a parent that no longer exists must restart the walk, not skip everything.
        [(11, [11]), (999, [10, 11])],
    )
    def test_resumes_from_bookmarked_parent(self, bookmarked_parent_id, expected_team_ids):
        result = _driver().run(
            "team_members",
            [
                ScriptedResponse(json=[{"id": 10}, {"id": 11}]),
                *[ScriptedResponse(json=[{"id": 5}]) for _ in expected_team_ids],
            ],
            resume_state=ChatwootResumeConfig(parent_id=bookmarked_parent_id),
        )

        assert [row["team_id"] for row in result.rows] == expected_team_ids
        assert result.paths[1:] == [f"/api/v1/accounts/1/teams/{team_id}/team_members" for team_id in expected_team_ids]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot.MAX_MEMBER_FANOUT_PARENTS",
        1,
    )
    def test_parent_fanout_stops_at_the_parent_cap(self):
        # A misbehaving server can return an unbounded parent list, and the fan-out issues one
        # request per parent.
        result = _driver().run(
            "team_members", [ScriptedResponse(json=[{"id": 10}, {"id": 11}]), ScriptedResponse(json=[{"id": 1}])]
        )

        assert [row["team_id"] for row in result.rows] == [10]
        assert not any("/teams/11/" in path for path in result.paths)


class TestGetRowsReportingEvents:
    @pytest.mark.parametrize(
        "watermark, expected_since",
        [
            # Chatwoot drops the filter unless both bounds are present, so a full refresh sends
            # epoch 0 rather than omitting `since`.
            (None, 0),
            ("2026-01-02T03:04:05+00:00", 1767323045),
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), 1767323045),
            # An unusable watermark must widen the window, never narrow it to an arbitrary date.
            ("not-a-date", 0),
        ],
    )
    def test_walks_pages_within_a_pinned_window_and_stops_at_total_pages(self, watermark, expected_since):
        result = _driver().run(
            "reporting_events",
            [
                ScriptedResponse(
                    json={"meta": {"count": 3, "current_page": 1, "total_pages": 2}, "payload": [{"id": 1}, {"id": 2}]}
                ),
                ScriptedResponse(
                    json={"meta": {"count": 3, "current_page": 2, "total_pages": 2}, "payload": [{"id": 3}]}
                ),
            ],
            incremental_field="created_at",
            db_incremental_field_last_value=watermark,
        )

        assert [row["id"] for row in result.rows] == [1, 2, 3]
        # total_pages ends the walk, so no third request is made.
        assert len(result.requests) == 2
        assert result.params("since") == [str(expected_since)] * 2
        # Chatwoot orders this endpoint newest-first over page numbers, so the window end has to
        # be identical on every page or rows at each boundary are skipped as events arrive.
        untils = set(result.params("until"))
        assert len(untils) == 1
        # Saved state carries that window so a resumed attempt paginates the same one.
        assert result.saved_states == [
            ChatwootResumeConfig(page=2, until=int(untils.pop() or "0")),
            ChatwootResumeConfig(page=3, until=result.saved_states[0].until),
        ]

    def test_missing_total_pages_falls_back_to_the_empty_page(self):
        result = _driver().run(
            "reporting_events",
            [ScriptedResponse(json={"payload": [{"id": 1}]}), ScriptedResponse(json={"payload": []})],
        )

        assert [row["id"] for row in result.rows] == [1]
        assert result.params("page") == ["1", "2"]

    def test_resume_reuses_the_saved_window(self):
        # Recomputing "now" on a resumed attempt would renumber every remaining page.
        result = _driver().run(
            "reporting_events",
            [ScriptedResponse(json={"meta": {}, "payload": []})],
            resume_state=ChatwootResumeConfig(page=4, until=1767000000),
            incremental_field="created_at",
            db_incremental_field_last_value="2026-01-02T03:04:05+00:00",
        )

        assert result.params("page") == ["4"]
        assert result.params("until") == ["1767000000"]

    def test_404_reports_the_endpoint_as_unavailable_not_a_missing_account(self):
        # The route only exists on enterprise builds. The generic 404 message would send the user
        # off to re-check an account id that is correct.
        result = _driver().run("reporting_events", [ScriptedResponse(status=404, json={"error": "Not Found"})])

        assert isinstance(result.raised, Exception)
        assert REPORTING_EVENTS_UNAVAILABLE_ERROR in str(result.raised)


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

    def test_rows_without_an_id_are_dropped(self):
        transform = make_webhook_table_transformer("conversations")
        table = table_from_py_list([{"event": "conversation_created", "status": "open", "id": None}])

        assert transform(table).num_rows == 0


class TestWebhookManagement:
    def test_create_webhook_returns_signing_secret_as_extra_input(self):
        with scripted_network(
            [
                ScriptedResponse(
                    json={"payload": {"webhook": {"id": 3, "url": "https://ph/webhook", "secret": "s3cret"}}}
                )
            ]
        ) as network:
            result = create_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "s3cret"}
        assert result.pending_inputs == []
        assert network.requests_log[0].method == "POST"
        body = network.requests_log[0].json()
        assert body["webhook"]["url"] == "https://ph/webhook"
        assert set(body["webhook"]["subscriptions"]) == {
            "conversation_created",
            "conversation_updated",
            "conversation_status_changed",
            "message_created",
            "message_updated",
        }

    def test_create_webhook_without_secret_marks_signing_secret_pending(self):
        # Older self-hosted Chatwoot versions have no per-webhook secret.
        with scripted_network(
            [ScriptedResponse(json={"payload": {"webhook": {"id": 3, "url": "https://ph/webhook"}}})]
        ):
            result = create_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]

    @pytest.mark.parametrize("status", [401, 403])
    def test_create_webhook_permission_error_is_actionable(self, status):
        with scripted_network([ScriptedResponse(status=status, json={"error": "nope"})]):
            result = create_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is False
        assert result.error is not None and "administrator" in result.error

    def test_create_webhook_reconciles_existing_webhook_on_422(self):
        # Webhook URLs are unique per account: a partial earlier setup 422s on re-create.
        with scripted_network(
            [
                ScriptedResponse(status=422, json={"message": "URL has already been taken"}),
                ScriptedResponse(
                    json={
                        "payload": {
                            "webhooks": [{"id": 9, "url": "https://ph/webhook", "subscriptions": ["message_created"]}]
                        }
                    }
                ),
                ScriptedResponse(
                    json={"payload": {"webhook": {"id": 9, "url": "https://ph/webhook", "secret": "s3cret"}}}
                ),
            ]
        ) as network:
            result = create_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "s3cret"}
        assert [request.method for request in network.requests_log] == ["POST", "GET", "PATCH"]
        assert network.requests_log[-1].path == "/api/v1/accounts/1/webhooks/9"

    def test_delete_webhook_is_a_noop_success_when_absent(self):
        with scripted_network([ScriptedResponse(json={"payload": {"webhooks": []}})]) as network:
            result = delete_webhook(None, "1", "token", "https://ph/webhook", TEAM_ID, mock.MagicMock())

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET"]


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
    def test_fanout_primary_keys_include_the_parent_id(self, config):
        # A fan-out child aggregates rows from every parent, so a key that is only unique per
        # parent seeds duplicates that every later merge multi-matches.
        if config.parent_id_field:
            assert config.parent_id_field in config.primary_keys

    def test_webhook_enabled_schema_reads_from_webhook_manager(self):
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        response = chatwoot_source(
            None, "1", "token", "conversations", TEAM_ID, mock.MagicMock(), _make_manager(), webhook_manager
        )
        response.items()

        webhook_manager.get_items.assert_called_once()
