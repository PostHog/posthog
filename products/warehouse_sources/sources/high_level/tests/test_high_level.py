from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from requests import ConnectionError as RequestsConnectionError

from products.warehouse_sources.sources.high_level._config import HighLevelSourceConfig
from products.warehouse_sources.sources.high_level.high_level import HighLevelResumeConfig
from products.warehouse_sources.sources.high_level.source import HighLevelSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)

TOKEN = "pit-test-token"
LOCATION_ID = "loc_ABC123"


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 3, 15, 12, 0, tzinfo=UTC), tick=False):
        yield


def _driver(location_id: str = LOCATION_ID) -> SourceDriver:
    return SourceDriver(
        HighLevelSource(), HighLevelSourceConfig(private_integration_token=TOKEN, location_id=location_id)
    )


def _contact(contact_id: str) -> dict[str, Any]:
    return {"id": contact_id, "dateUpdated": "2026-03-01T10:00:00.000Z", "searchAfter": [1772359200000, contact_id]}


class TestContacts:
    def test_walks_search_after_pages_until_has_more_is_false(self) -> None:
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json={"contacts": [_contact("c1"), _contact("c2")], "hasMore": True}),
                ScriptedResponse(json={"contacts": [_contact("c3")], "hasMore": False}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c1", "c2", "c3"]
        assert [request.method for request in result.requests] == ["POST", "POST"]
        assert result.paths == ["/contacts/search", "/contacts/search"]
        first, second = (request.json() for request in result.requests)
        assert "searchAfter" not in first
        assert second["searchAfter"] == [1772359200000, "c2"]
        assert "page" not in second
        assert result.requests[0].headers["version"] == "v3"
        assert result.requests[0].headers["authorization"] == f"Bearer {TOKEN}"

    @pytest.mark.parametrize(
        ("incremental", "last_value", "expected_filters", "expected_sort_field"),
        [
            (False, None, None, "dateAdded"),
            (
                True,
                datetime(2026, 3, 1, 9, 30, 15, 123456, tzinfo=UTC),
                [{"field": "dateUpdated", "operator": "range", "value": {"gte": "2026-03-01T09:30:15.123Z"}}],
                "dateUpdated",
            ),
            (
                True,
                "2026-03-01T09:30:15.123Z",
                [{"field": "dateUpdated", "operator": "range", "value": {"gte": "2026-03-01T09:30:15.123Z"}}],
                "dateUpdated",
            ),
        ],
    )
    def test_request_body_matches_the_sync_mode(
        self,
        incremental: bool,
        last_value: Any,
        expected_filters: list[dict[str, Any]] | None,
        expected_sort_field: str,
    ) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json={"contacts": [], "hasMore": False})],
            incremental_field="dateUpdated",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        body = result.requests[0].json()
        assert body["locationId"] == LOCATION_ID
        assert body["pageLimit"] == 500
        assert body.get("filters") == expected_filters
        assert body["sort"] == [{"field": expected_sort_field, "direction": "asc"}]

    def test_a_page_without_a_next_cursor_fails_instead_of_truncating(self) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json={"contacts": [{"id": "c1"}], "hasMore": True})],
        )

        assert isinstance(result.raised, ValueError)

    def test_resumes_from_the_saved_search_after_cursor(self) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json={"contacts": [_contact("c9")], "hasMore": False})],
            resume_state=HighLevelResumeConfig(paginator_state={"cursor": {"searchAfter": [1, "c8"]}}),
        )

        assert result.raised is None
        assert result.requests[0].json()["searchAfter"] == [1, "c8"]

    def test_saves_the_cursor_with_the_page_it_follows(self) -> None:
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json={"contacts": [_contact("c1")], "hasMore": True}),
                ScriptedResponse(json={"contacts": [_contact("c2")], "hasMore": False}),
            ],
        )

        assert result.committed_states == [
            HighLevelResumeConfig(paginator_state={"cursor": {"searchAfter": [1772359200000, "c1"]}})
        ]


class TestKeysetEndpoints:
    def test_opportunities_page_with_meta_cursor_until_next_page_is_null(self) -> None:
        result = _driver().run(
            "opportunities",
            [
                ScriptedResponse(
                    json={
                        "opportunities": [{"id": "o1"}, {"id": "o2"}],
                        "meta": {"startAfter": 1700000000000, "startAfterId": "o2", "nextPage": 2},
                    }
                ),
                ScriptedResponse(
                    json={
                        "opportunities": [{"id": "o3"}],
                        "meta": {"startAfter": 1700000005000, "startAfterId": "o3", "nextPage": None},
                    }
                ),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["o1", "o2", "o3"]
        assert result.params("locationId") == [LOCATION_ID, LOCATION_ID]
        assert result.params("startAfterId") == [None, "o2"]
        assert result.params("startAfter") == [None, "1700000000000"]

    @pytest.mark.parametrize(
        ("last_row", "expected_cursor"),
        [
            ({"id": "v2", "sort": [1700000000000], "lastMessageDate": 1600000000000}, "1700000000000"),
            ({"id": "v2", "lastMessageDate": 1600000000000}, "1600000000000"),
        ],
    )
    def test_conversations_page_with_the_last_sort_value_until_an_empty_page(
        self, last_row: dict[str, Any], expected_cursor: str
    ) -> None:
        result = _driver().run(
            "conversations",
            [
                ScriptedResponse(json={"conversations": [{"id": "v1", "sort": [1]}, last_row], "total": 2}),
                ScriptedResponse(json={"conversations": [], "total": 2}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["v1", "v2"]
        assert result.params("startAfterDate") == [None, expected_cursor]
        assert result.params("sortBy") == ["last_message_date", "last_message_date"]


class TestDateFilteredEndpoints:
    @pytest.mark.parametrize(
        ("schema_name", "channel"),
        [("messages", None), ("email_messages", "Email")],
    )
    def test_messages_follow_next_cursor_and_filter_on_the_watermark(
        self, schema_name: str, channel: str | None
    ) -> None:
        result = _driver().run(
            schema_name,
            [
                ScriptedResponse(json={"messages": [{"id": "m1"}], "nextCursor": "cur-2"}),
                ScriptedResponse(json={"messages": [{"id": "m2"}], "nextCursor": None}),
            ],
            incremental_field="dateAdded",
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["m1", "m2"]
        assert result.params("cursor") == [None, "cur-2"]
        assert result.params("startDate") == ["2026-03-01T00:00:00.000Z"] * 2
        assert result.params("sortOrder") == ["asc", "asc"]
        assert result.params("channel") == [channel, channel]

    def test_messages_full_refresh_sends_no_start_date(self) -> None:
        result = _driver().run(
            "messages",
            [ScriptedResponse(json={"messages": [], "nextCursor": None})],
            incremental_field="dateAdded",
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.params("startDate") == [None]

    @pytest.mark.parametrize(
        ("schema_name", "incremental", "expected_start_at"),
        [
            ("form_submissions", False, "2000-01-01"),
            ("form_submissions", True, "2026-02-20"),
            ("survey_submissions", True, "2026-02-20"),
        ],
    )
    def test_submissions_send_an_explicit_date_window_on_every_page(
        self, schema_name: str, incremental: bool, expected_start_at: str
    ) -> None:
        result = _driver().run(
            schema_name,
            [
                ScriptedResponse(json={"submissions": [{"id": "s1"}], "meta": {"nextPage": 2}}),
                ScriptedResponse(json={"submissions": [], "meta": {"nextPage": None}}),
            ],
            incremental_field="createdAt",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=datetime(2026, 2, 20, 23, 59, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.params("startAt") == [expected_start_at] * 2
        assert result.params("endAt") == ["2026-03-16"] * 2


class TestLocationScoping:
    @pytest.mark.parametrize(
        ("schema_name", "response", "expected_path", "expected_params"),
        [
            ("pipelines", {"pipelines": []}, "/opportunities/pipelines", {"locationId": LOCATION_ID}),
            ("custom_fields", {"customFields": []}, f"/locations/{LOCATION_ID}/customFields", {}),
            (
                "invoices",
                {"invoices": [], "total": 0},
                "/invoices/",
                {"altId": LOCATION_ID, "altType": "location", "offset": "0", "limit": "100"},
            ),
            ("forms", {"forms": [], "total": 0}, "/forms/", {"locationId": LOCATION_ID, "skip": "0", "limit": "50"}),
        ],
    )
    def test_each_endpoint_scopes_the_request_to_the_location(
        self, schema_name: str, response: dict[str, Any], expected_path: str, expected_params: dict[str, str]
    ) -> None:
        result = _driver().run(schema_name, [ScriptedResponse(json=response)])

        assert result.raised is None
        assert result.paths == [expected_path]
        assert {name: values[0] for name, values in result.requests[0].query.items()} == expected_params

    def test_a_location_id_that_could_change_the_path_is_refused(self) -> None:
        result = _driver(location_id="../users").run("custom_fields", [])

        assert isinstance(result.raised, ValueError)
        assert result.requests == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("schema_name", "status", "body", "expected_valid", "expected_message_part"),
        [
            (None, 200, {"location": {"id": LOCATION_ID}}, True, None),
            (None, 401, {"statusCode": 401, "message": "The token is not authorized for this scope."}, True, None),
            (
                "contacts",
                401,
                {"statusCode": 401, "message": "The token is not authorized for this scope."},
                False,
                "`contacts.readonly` scope",
            ),
            (
                None,
                401,
                {"statusCode": 401, "message": "Invalid token: access token is invalid", "error": "Unauthorized"},
                False,
                "rejected the private integration token",
            ),
            (
                None,
                403,
                {"statusCode": 403, "message": "The token does not have access to this location."},
                False,
                "location ID",
            ),
            ("contacts", 200, {"contacts": [], "hasMore": False}, True, None),
            ("invoices", 200, {"invoices": [], "total": 0}, True, None),
        ],
    )
    def test_maps_the_probe_answer_to_a_result(
        self,
        schema_name: str | None,
        status: int,
        body: dict[str, Any],
        expected_valid: bool,
        expected_message_part: str | None,
    ) -> None:
        config = HighLevelSourceConfig(private_integration_token=TOKEN, location_id=LOCATION_ID)
        with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
            valid, message = HighLevelSource().validate_credentials(config, team_id=1, schema_name=schema_name)

        assert valid is expected_valid
        if expected_message_part is None:
            assert message is None
        else:
            assert message is not None and expected_message_part in message
        request = network.requests_log[0]
        assert request.headers["version"] == "v3"
        if schema_name == "contacts":
            assert request.method == "POST"
            assert request.json()["pageLimit"] == 1
        elif schema_name == "invoices":
            assert {name: values[0] for name, values in request.query.items()} == {
                "altId": LOCATION_ID,
                "altType": "location",
                "offset": "0",
                "limit": "1",
            }
        else:
            assert request.path == f"/locations/{LOCATION_ID}"

    def test_unreachable_api_is_not_reported_as_bad_credentials(self) -> None:
        config = HighLevelSourceConfig(private_integration_token=TOKEN, location_id=LOCATION_ID)
        with scripted_network(always(RequestsConnectionError("connection reset"))):
            valid, message = HighLevelSource().validate_credentials(config, team_id=1)

        assert valid is False
        assert message is not None and "token" not in message

    def test_rejects_a_malformed_location_id_without_a_request(self) -> None:
        config = HighLevelSourceConfig(private_integration_token=TOKEN, location_id="acme.com/x")
        with scripted_network(route({})) as network:
            valid, message = HighLevelSource().validate_credentials(config, team_id=1)

        assert valid is False
        assert message is not None and "location ID" in message
        assert network.requests_log == []
