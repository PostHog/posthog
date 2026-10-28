from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trello import TrelloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.settings import TRELLO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.source import TrelloSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello import (
    TrelloResumeConfig,
    _add_created_at,
    _format_incremental_value,
    _id_to_created_at,
    validate_credentials,
)


def _json(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _run(
    endpoint: str,
    script: list[ScriptedResponse],
    resume_state: TrelloResumeConfig | None = None,
    **kwargs: Any,
) -> DriveResult:
    driver = SourceDriver(TrelloSource(), TrelloSourceConfig(api_key="key", api_token="token"))
    return driver.run(endpoint, script, resume_state=resume_state, **kwargs)


class TestIdToCreatedAt:
    @parameterized.expand(
        [
            # 0x5abbe394 = 1522242964 = 2018-03-28T18:48:52+00:00
            ("valid_object_id", "5abbe394c78f17ffa9e10843", "2018-03-28T18:48:52+00:00"),
            ("too_short", "abc", None),
            ("non_hex_prefix", "zzzzzzzzc78f17ffa9e10843", None),
            ("not_a_string", 12345, None),
            ("none", None, None),
        ]
    )
    def test_id_to_created_at(self, _name: str, obj_id: Any, expected: str | None) -> None:
        assert _id_to_created_at(obj_id) == expected


class TestAddCreatedAt:
    def test_injects_created_at_from_id(self) -> None:
        item = _add_created_at({"id": "5abbe394c78f17ffa9e10843", "name": "Board"})
        assert item["created_at"] == "2018-03-28T18:48:52+00:00"


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC), "2026-01-15T10:00:00+00:00"),
            ("naive_datetime", datetime(2026, 1, 15, 10, 0, 0), "2026-01-15T10:00:00+00:00"),
            ("date", date(2026, 1, 15), "2026-01-15T00:00:00+00:00"),
            ("string_passthrough", "2026-01-15T10:00:00Z", "2026-01-15T10:00:00Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("missing_token", 400, False, "Invalid Trello API key or token"),
        ]
    )
    def test_status_codes(self, _name: str, status: int, valid: bool, message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]):
            result_valid, result_message = validate_credentials("key", "token")

        assert result_valid is valid
        assert result_message == message


class TestMemberEndpoint:
    def test_boards_single_request_injects_created_at(self) -> None:
        boards = [{"id": "5abbe394c78f17ffa9e10843", "name": "A"}, {"id": "5abbe395c78f17ffa9e10843", "name": "B"}]

        result = _run("boards", [_json(boards)])

        assert [r["name"] for r in result.rows] == ["A", "B"]
        assert all("created_at" in r for r in result.rows)
        # Member endpoints are a single request; no resume checkpoints.
        assert result.saved_states == []
        assert result.requests[0].url.split("?")[0] == "https://api.trello.com/1/members/me/boards"
        assert result.requests[0].param("limit") == "1000"

    def test_non_list_body_fails_loud(self) -> None:
        result = _run("organizations", [_json({"error": "nope"})])

        # A 200 whose body isn't a list means the response shape changed — fail loud rather than
        # wrapping the stray object as a single row.
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestActionsIncremental:
    def test_incremental_sends_since_and_limit(self) -> None:
        cutoff = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)

        result = _run(
            "actions",
            [
                _json([{"id": "b1"}]),
                _json([{"id": "a1", "date": "2026-02-01T00:00:00Z"}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
        )

        actions_request = result.requests[1]
        assert actions_request.url.split("?")[0] == "https://api.trello.com/1/boards/b1/actions"
        assert actions_request.param("since") == "2026-01-15T10:00:00+00:00"
        assert actions_request.param("limit") == "1000"

    def test_paginates_with_before_cursor(self) -> None:
        # Drive pagination with a small page size instead of 1000 rows.
        with mock.patch.object(TRELLO_ENDPOINTS["actions"], "page_size", 2):
            result = _run(
                "actions",
                [
                    _json([{"id": "b1"}]),
                    _json([{"id": "a1"}, {"id": "a2"}]),  # full page (limit 2) → keep paging
                    _json([{"id": "a3"}]),  # short page → stop
                ],
            )

        assert [r["id"] for r in result.rows] == ["a1", "a2", "a3"]
        # First actions page carries no cursor; the second pages back with before=<oldest of page 1>.
        assert result.requests[1].param("before") is None
        assert result.requests[2].param("before") == "a2"
        # Board fully drained → final checkpoint records it completed, nothing in progress.
        final_state = result.saved_states[-1].fanout_state
        assert final_state["completed"] == ["/boards/b1/actions"]
        assert final_state["current"] is None

    def test_resume_uses_before_cursor(self) -> None:
        result = _run(
            "actions",
            [_json([{"id": "b1"}]), _json([{"id": "a1"}])],
            resume_state=TrelloResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/boards/b1/actions",
                    "child_state": {"before": "oldest"},
                }
            ),
        )

        assert result.requests[1].param("before") == "oldest"


class TestTrelloSourceResponse:
    @parameterized.expand(
        [
            ("boards", "asc", "id"),
            ("actions", "desc", "id"),
            ("cards", "asc", "id"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, sort_mode: str, primary_key: str) -> None:
        response = _run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.sort_mode == sort_mode
        assert response.primary_keys == [primary_key]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"

    @parameterized.expand([(name,) for name in TRELLO_ENDPOINTS])
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = _run(endpoint, []).response
        assert response is not None
        assert callable(response.items)
        assert response.primary_keys == [TRELLO_ENDPOINTS[endpoint].primary_key]
