from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import pyarrow as pa

from products.warehouse_sources.sources.nylas._config import NylasSourceConfig
from products.warehouse_sources.sources.nylas.nylas import (
    NylasConnection,
    NylasResumeConfig,
    make_webhook_table_transformer,
    parse_grant_ids,
)
from products.warehouse_sources.sources.nylas.settings import NYLAS_ENDPOINTS
from products.warehouse_sources.sources.nylas.source import NylasSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route

GRANTS = "/v3/grants"

# Verbatim Nylas error envelope for a rejected API key.
INVALID_API_KEY = {
    "request_id": "5967ca40-a2d8-4ee0-a0e0-6f18ace39a90",
    "error": {"type": "token.unauthorized_access", "message": "Invalid API Key"},
}


def _driver(**config: Any) -> SourceDriver:
    return SourceDriver(NylasSource(), NylasSourceConfig(api_key="nyk_test", **config))


def _grant(grant_id: str, provider: str = "google", status: str = "valid") -> dict[str, Any]:
    return {"id": grant_id, "provider": provider, "grant_status": status, "created_at": 1700000000}


def _grants(*grants: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json={"request_id": "r", "data": list(grants), "limit": 200, "offset": 0})


def _page(rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"request_id": "r", "data": rows, "next_cursor": next_cursor})


def _messages(grant_id: str) -> str:
    return f"/v3/grants/{grant_id}/messages"


class TestPerGrantWalk:
    def test_walks_every_page_of_every_valid_grant_and_stages_the_cursor_before_each_batch(self) -> None:
        result = _driver().run(
            "messages",
            route(
                {
                    _messages("g1"): [
                        _page([{"id": "m1", "grant_id": "g1", "date": 10}], next_cursor="c2"),
                        _page([{"id": "m2", "date": 9}]),
                    ],
                    _messages("g2"): [_page([{"id": "m1", "grant_id": "g2", "date": 8}])],
                    GRANTS: [_grants(_grant("g1"), _grant("dead", status="invalid"), _grant("g2"))],
                }
            ),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.paths == [GRANTS, _messages("g1"), _messages("g1"), _messages("g2")]
        assert result.params("page_token") == [None, None, "c2", None]
        assert result.params("limit")[1:] == ["100", "100", "100"]
        # The same provider message ID in two grants stays two rows, and a row without a
        # grant_id takes it from the grant it was read from.
        assert [(row["grant_id"], row["id"]) for row in result.rows] == [("g1", "m1"), ("g1", "m2"), ("g2", "m1")]
        assert result.response is not None
        assert result.response.primary_keys == ["grant_id", "id"]
        assert result.committed_states == [
            NylasResumeConfig(grant_id="g1", unit="", page_token="c2"),
            NylasResumeConfig(grant_id="g2"),
        ]

    def test_resumes_from_the_saved_grant_and_page(self) -> None:
        result = _driver().run(
            "messages",
            route(
                {
                    _messages("g2"): [_page([{"id": "m9", "grant_id": "g2", "date": 1}])],
                    GRANTS: [_grants(_grant("g1"), _grant("g2"))],
                }
            ),
            resume_state=NylasResumeConfig(grant_id="g2", unit="", page_token="c7"),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.paths == [GRANTS, _messages("g2")]
        assert result.params("page_token") == [None, "c7"]

    @pytest.mark.parametrize(
        ("schema", "watermark", "param", "expected"),
        [
            ("messages", 1700000100, "received_after", "1700000099"),
            ("messages", datetime(2023, 11, 14, 22, 15, tzinfo=UTC), "received_after", "1700000099"),
            ("messages", None, "received_after", None),
        ],
    )
    def test_incremental_run_sends_the_watermark_on_every_page(
        self, schema: str, watermark: Any, param: str, expected: str | None
    ) -> None:
        path = f"/v3/grants/g1/{schema}"
        result = _driver().run(
            schema,
            route(
                {
                    path: [_page([{"id": "a", "grant_id": "g1"}], next_cursor="c2"), _page([])],
                    GRANTS: [_grants(_grant("g1"))],
                }
            ),
            incremental_field=NylasSource()
            .get_schemas(NylasSourceConfig(api_key="k"), 1, names=[schema])[0]
            .incremental_fields[0]["field"],
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.params(param)[1:] == [expected, expected]

    def test_full_refresh_sends_no_watermark(self) -> None:
        result = _driver().run(
            "messages",
            route({_messages("g1"): [_page([])], GRANTS: [_grants(_grant("g1"))]}),
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000100,
        )

        assert result.params("received_after") == [None, None]

    @pytest.mark.parametrize(
        ("config", "expected_grants"),
        [
            ({}, ["g_google", "g_agent"]),
            ({"grant_scope": "agent_accounts"}, ["g_agent"]),
            ({"grant_scope": "connected_accounts"}, ["g_google"]),
            ({"grant_ids": "g_agent, missing"}, ["g_agent"]),
            ({"grant_scope": "connected_accounts", "grant_ids": "g_agent"}, []),
        ],
    )
    def test_only_reads_grants_in_the_configured_scope(
        self, config: dict[str, Any], expected_grants: list[str]
    ) -> None:
        result = _driver(**config).run(
            "folders",
            route(
                {
                    "/v3/grants/g_google/folders": [_page([{"id": "INBOX"}])],
                    "/v3/grants/g_agent/folders": [_page([{"id": "INBOX"}])],
                    GRANTS: [_grants(_grant("g_google"), _grant("g_agent", provider="nylas"))],
                }
            ),
        )

        assert result.raised is None
        assert result.paths[1:] == [f"/v3/grants/{grant}/folders" for grant in expected_grants]
        assert [row["grant_id"] for row in result.rows] == expected_grants


class TestEvents:
    CALENDARS = "/v3/grants/g1/calendars"
    EVENTS = "/v3/grants/g1/events"

    def _run(self, provider: str, calendars: list[str], pages: int, **inputs: Any) -> Any:
        return _driver(event_history_days=30).run(
            "events",
            route(
                {
                    self.CALENDARS: [_page([{"id": calendar} for calendar in calendars])],
                    self.EVENTS: [_page([{"id": f"e{i}", "calendar_id": "c", "updated_at": 5}]) for i in range(pages)],
                    GRANTS: [_grants(_grant("g1", provider=provider))],
                }
            ),
            **inputs,
        )

    def test_reads_every_calendar_over_an_explicit_time_range(self) -> None:
        # Without a range Nylas only returns the coming month.
        result = self._run("google", ["primary", "team"], pages=2, should_use_incremental_field=False)

        assert result.raised is None
        assert result.paths == [GRANTS, self.CALENDARS, self.EVENTS, self.EVENTS]
        assert result.params("calendar_id")[2:] == ["primary", "team"]
        midnight = datetime.combine(datetime.now(UTC).date(), datetime.min.time(), tzinfo=UTC)
        assert result.params("start")[2:] == [str(int((midnight - timedelta(days=30)).timestamp()))] * 2
        assert result.params("end")[2:] == [str(int((midnight + timedelta(days=365)).timestamp()))] * 2
        assert result.params("expand_recurring")[2:] == ["false", "false"]
        assert result.params("show_cancelled")[2:] == ["true", "true"]
        assert result.response is not None
        assert result.response.primary_keys == ["grant_id", "calendar_id", "id"]
        assert result.committed_states[0].unit.startswith("team|")

    def test_icloud_grants_get_ranges_of_six_months_or_less_and_no_cancelled_filter(self) -> None:
        # 30 days back plus 365 days ahead is three ranges.
        result = self._run("icloud", ["primary"], pages=3, should_use_incremental_field=False)

        assert result.raised is None
        event_requests = [request for request in result.requests if request.path == self.EVENTS]
        assert len(event_requests) == 3
        assert {request.param("show_cancelled") for request in event_requests} == {None}
        spans = [int(request.param("end") or 0) - int(request.param("start") or 0) for request in event_requests]
        assert all(0 < span <= 180 * 86400 for span in spans)

    def test_resumes_inside_the_saved_calendar(self) -> None:
        first = self._run("google", ["primary", "team"], pages=2, should_use_incremental_field=False)
        bookmark = first.committed_states[0]

        resumed = _driver(event_history_days=30).run(
            "events",
            route(
                {
                    self.CALENDARS: [_page([{"id": "primary"}, {"id": "team"}])],
                    self.EVENTS: [_page([{"id": "e9", "calendar_id": "team"}])],
                    GRANTS: [_grants(_grant("g1"))],
                }
            ),
            resume_state=NylasResumeConfig(grant_id="g1", unit=bookmark.unit, page_token="c3"),
            should_use_incremental_field=False,
        )

        assert resumed.raised is None
        assert resumed.params("calendar_id")[2:] == ["team"]
        assert resumed.params("page_token")[2:] == ["c3"]

    def test_a_grant_without_calendar_access_is_skipped(self) -> None:
        result = _driver().run(
            "events",
            route(
                {
                    "/v3/grants/mail_only/calendars": [
                        ScriptedResponse(status=403, json={"error": {"type": "forbidden"}})
                    ],
                    self.CALENDARS: [_page([])],
                    GRANTS: [_grants(_grant("mail_only"), _grant("g1")), _grants(_grant("g1"))],
                }
            ),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.rows == []


class TestGrantLevelFailures:
    def test_a_deleted_grant_is_skipped_and_the_walk_continues(self) -> None:
        result = _driver().run(
            "messages",
            route(
                {
                    _messages("gone"): [ScriptedResponse(status=404, json={"error": {"type": "not_found_error"}})],
                    "/v3/grants/gone": [ScriptedResponse(status=404, json={"error": {"type": "not_found_error"}})],
                    _messages("g2"): [_page([{"id": "m1", "grant_id": "g2"}])],
                    GRANTS: [_grants(_grant("gone"), _grant("g2"))],
                }
            ),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert [row["grant_id"] for row in result.rows] == ["g2"]

    def test_a_404_for_a_grant_that_still_exists_fails_the_sync(self) -> None:
        # Nylas answered 404 to a list request it could not serve for a working grant. Skipping
        # the grant there would end the sync with no rows and no error.
        result = _driver().run(
            "messages",
            route(
                {
                    _messages("g1"): [ScriptedResponse(status=404, json={"error": {"message": "Not Found"}})],
                    "/v3/grants/g1": [ScriptedResponse(json={"data": _grant("g1")})],
                    GRANTS: [_grants(_grant("g1"))],
                }
            ),
            should_use_incremental_field=False,
        )

        assert result.rows == []
        assert "404 Client Error" in str(result.raised)

    def test_a_grant_whose_provider_has_no_such_data_is_skipped_but_another_400_fails(self) -> None:
        # Verbatim Nylas error for the messages of a virtual calendar grant.
        unsupported = {
            "request_id": "3d1e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f60",
            "error": {"type": "general_error", "message": "Method not supported for provider: virtual-calendar"},
        }
        script = {
            _messages("vcal"): [ScriptedResponse(status=400, json=unsupported)],
            _messages("g2"): [_page([{"id": "m1", "grant_id": "g2"}])],
            GRANTS: [_grants(_grant("vcal", provider="virtual-calendar"), _grant("g2"))],
        }
        skipped = _driver().run("messages", route(script), should_use_incremental_field=False)

        assert skipped.raised is None
        assert [row["grant_id"] for row in skipped.rows] == ["g2"]

        bad_request = {"error": {"type": "invalid_request_error", "message": "Invalid limit"}}
        failed = _driver().run(
            "messages",
            route({_messages("g1"): [ScriptedResponse(status=400, json=bad_request)], GRANTS: [_grants(_grant("g1"))]}),
            should_use_incremental_field=False,
        )

        assert "400 Client Error" in str(failed.raised)

    def test_a_grant_that_lost_authorization_is_skipped_while_the_api_key_still_works(self) -> None:
        result = _driver().run(
            "messages",
            route(
                {
                    _messages("expired"): [ScriptedResponse(status=401, json={"error": {"type": "unauthorized"}})],
                    _messages("g2"): [_page([{"id": "m1", "grant_id": "g2"}])],
                    GRANTS: [_grants(_grant("expired"), _grant("g2")), _grants(_grant("expired"))],
                }
            ),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert [row["grant_id"] for row in result.rows] == ["g2"]

    def test_a_revoked_api_key_fails_the_sync_instead_of_skipping_every_grant(self) -> None:
        result = _driver().run(
            "messages",
            route(
                {
                    _messages("g1"): [ScriptedResponse(status=401, json=INVALID_API_KEY)],
                    GRANTS: [_grants(_grant("g1"), _grant("g2")), ScriptedResponse(status=401, json=INVALID_API_KEY)],
                }
            ),
            should_use_incremental_field=False,
        )

        assert result.rows == []
        assert "401 Client Error: Unauthorized for url: https://api.us.nylas.com" in str(result.raised)


class TestGrantsTable:
    def test_pages_by_offset_until_a_short_page_and_resumes_from_the_saved_offset(self) -> None:
        full_page = [_grant(f"g{i}") for i in range(200)]

        result = _driver(region="eu").run("grants", [_grants(*full_page), _grants(_grant("last"))])

        assert result.raised is None
        assert {request.origin for request in result.requests} == {"https://api.eu.nylas.com"}
        assert result.params("offset") == ["0", "200"]
        assert result.params("order_by") == ["asc", "asc"]
        assert len(result.rows) == 201
        assert result.committed_states == [NylasResumeConfig(offset=200)]

        resumed = _driver().run("grants", [_grants(_grant("last"))], resume_state=NylasResumeConfig(offset=200))

        assert resumed.params("offset") == ["200"]


class TestMessageBodies:
    def test_bodies_are_removed_from_messages_and_from_the_message_inside_a_thread(self) -> None:
        driver = _driver(include_message_bodies=False)

        messages = driver.run(
            "messages",
            route(
                {
                    _messages("g1"): [_page([{"id": "m1", "subject": "Hi", "body": "<p>secret</p>"}])],
                    GRANTS: [_grants(_grant("g1"))],
                }
            ),
            should_use_incremental_field=False,
        )
        threads = driver.run(
            "threads",
            route(
                {
                    "/v3/grants/g1/threads": [
                        _page([{"id": "t1", "latest_draft_or_message": {"id": "m1", "body": "<p>secret</p>"}}])
                    ],
                    GRANTS: [_grants(_grant("g1"))],
                }
            ),
            should_use_incremental_field=False,
        )

        assert messages.rows == [{"id": "m1", "subject": "Hi", "grant_id": "g1"}]
        assert threads.rows == [{"id": "t1", "latest_draft_or_message": {"id": "m1"}, "grant_id": "g1"}]


def _notification(event_type: str, sent_at: int, message: dict[str, Any]) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "type": event_type,
        "id": f"evt-{sent_at}",
        "time": sent_at,
        "data": {"application_id": "app", "object": {"object": "message", **message}},
    }


class TestWebhookTableTransformer:
    def _transform(
        self,
        notifications: list[dict[str, Any]],
        connection: NylasConnection,
        allowed: frozenset[str] | None = None,
        table: str = "messages",
    ) -> list[dict[str, Any]]:
        transformer = make_webhook_table_transformer(connection, NYLAS_ENDPOINTS[table], lambda: allowed)
        return transformer(pa.Table.from_pylist(notifications)).to_pylist()

    def test_keeps_the_newest_notification_per_grant_and_message(self) -> None:
        rows = self._transform(
            [
                _notification("message.updated", 20, {"id": "m1", "grant_id": "g1", "unread": False}),
                _notification("message.created", 10, {"id": "m1", "grant_id": "g1", "unread": True}),
                _notification("message.created", 15, {"id": "m1", "grant_id": "g2", "unread": True}),
            ],
            NylasConnection(api_key="k"),
        )

        assert sorted((row["grant_id"], row["id"], row["unread"]) for row in rows) == [
            ("g1", "m1", False),
            ("g2", "m1", True),
        ]

    def test_drops_grants_outside_the_scope_and_removes_bodies_when_configured(self) -> None:
        rows = self._transform(
            [
                _notification("message.created", 10, {"id": "m1", "grant_id": "g1", "body": "<p>secret</p>"}),
                _notification("message.created", 11, {"id": "m2", "grant_id": "other", "body": "<p>secret</p>"}),
            ],
            NylasConnection(api_key="k", grant_scope="agent_accounts", include_message_bodies=False),
            allowed=frozenset({"g1"}),
        )

        assert rows == [{"object": "message", "id": "m1", "grant_id": "g1"}]

    def test_deleted_event_becomes_a_cancelled_row_keyed_by_calendar(self) -> None:
        deleted = {"grant_id": "g1", "calendar_id": "cal1", "id": "e1", "object": "event"}
        rows = self._transform(
            [
                {
                    "type": "event.updated",
                    "time": 10,
                    "data": {"object": {**deleted, "status": "confirmed", "title": "Sync"}},
                },
                {"type": "event.deleted", "time": 20, "data": {"object": deleted}},
                {
                    "type": "event.created",
                    "time": 5,
                    "data": {"object": {**deleted, "calendar_id": "cal2", "status": "confirmed"}},
                },
                # A message in the same batch belongs to another table.
                _notification("message.created", 30, {"id": "m1", "grant_id": "g1"}),
            ],
            NylasConnection(api_key="k"),
            table="events",
        )

        assert sorted((row["calendar_id"], row["status"]) for row in rows) == [
            ("cal1", "cancelled"),
            ("cal2", "confirmed"),
        ]

    def test_ignores_payloads_without_a_message(self) -> None:
        rows = self._transform(
            [
                {"type": "grant.expired", "time": 5, "data": {"object": {"grant_id": "g1", "code": 25009}}},
                _notification("message.created", 10, {"id": None, "grant_id": "g1"}),
            ],
            NylasConnection(api_key="k"),
        )

        assert rows == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, set()), ("", set()), ("a, b ,,\nc", {"a", "b", "c"})],
)
def test_parse_grant_ids(value: str | None, expected: set[str]) -> None:
    assert parse_grant_ids(value) == expected
