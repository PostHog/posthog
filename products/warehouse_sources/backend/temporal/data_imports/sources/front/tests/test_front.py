from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.front.front import (
    FrontResumeConfig,
    _resolve_after_value,
    _to_unix_seconds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.front.settings import FRONT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.front.source import FrontSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.front import FrontSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(FrontSource(), FrontSourceConfig(api_token="tok"))


def _page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"_results": rows, "_pagination": {"next": next_url}})


class TestToUnixSeconds:
    def test_aware_datetime(self) -> None:
        dt = datetime(2023, 1, 1, tzinfo=UTC)
        assert _to_unix_seconds(dt) == dt.timestamp()

    @parameterized.expand([("int", 1700000000), ("float", 1700000000.123)])
    def test_numeric_passthrough(self, _name: str, value: Any) -> None:
        assert _to_unix_seconds(value) == value


class TestResolveAfterValue:
    def test_lookback_used_when_no_last_value(self) -> None:
        result = _resolve_after_value(FRONT_ENDPOINTS["events"], True, None)
        # events has a 365-day lookback, so a float timestamp in the past is returned
        assert isinstance(result, float)
        assert result < datetime.now(UTC).timestamp()

    def test_no_lookback_no_last_value_returns_none(self) -> None:
        assert _resolve_after_value(FRONT_ENDPOINTS["contacts"], True, None) is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden_with_scope", 403, True, False),
            ("forbidden_without_scope", 403, False, True),
            ("not_found_token_valid", 404, False, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, require_scope: bool, expected_ok: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, _msg = validate_credentials("tok", "/teammates", require_scope=require_scope)

        assert ok is expected_ok
        assert [request.path for request in network.requests_log] == ["/teammates"]
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"

    def test_connection_error_fails(self) -> None:
        with scripted_network([ConnectionResetError("boom")]):
            ok, msg = validate_credentials("tok", "/teammates", require_scope=False)

        assert ok is False
        assert msg is not None


class TestPagination:
    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://api2.frontapp.com/events?page_token=resume"
        result = _driver().run(
            "events",
            [_page([{"id": "evt_9"}])],
            resume_state=FrontResumeConfig(next_url=resume_url),
        )

        assert [row["id"] for row in result.rows] == ["evt_9"]
        assert result.urls == [resume_url]

    def test_empty_page_does_not_terminate(self) -> None:
        # An empty `_results` page with a next link must keep paginating (deleted resources can
        # leave a page short without it being the last page).
        next_url = "https://api2.frontapp.com/tags?page_token=p2"
        result = _driver().run("tags", [_page([], next_url), _page([{"id": "tag_1"}])])

        assert [row["id"] for row in result.rows] == ["tag_1"]
        assert len(result.requests) == 2
        assert result.urls[1] == next_url

    def test_events_incremental_sends_q_after(self) -> None:
        result = _driver().run(
            "events",
            [_page([{"id": "evt_1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert result.requests[0].param("q[after]") == "1700000000"
        assert result.requests[0].param("limit") == "15"


class TestFanout:
    def test_fan_out_resume_skips_completed_parents(self) -> None:
        result = _driver().run(
            "conversation_messages",
            [
                _page([{"id": "cnv_1"}, {"id": "cnv_2"}]),
                _page([{"id": "msg_2"}]),
            ],
            resume_state=FrontResumeConfig(completed=["/conversations/cnv_1/messages"]),
        )

        assert [row["id"] for row in result.rows] == ["msg_2"]
        assert result.paths[1:] == ["/conversations/cnv_2/messages"]

    @parameterized.expand(
        [
            ("conversation_followers", "cnv", "conversation_id", "/conversations/{}/followers", None),
            ("teammate_group_teammates", "cir", "teammate_group_id", "/teammate_groups/{}/teammates", None),
            ("teammate_group_teams", "cir", "teammate_group_id", "/teammate_groups/{}/teams", None),
            ("teammate_group_inboxes", "cir", "teammate_group_id", "/teammate_groups/{}/inboxes", None),
            ("contact_list_contacts", "grp", "contact_list_id", "/contact_lists/{}/contacts", "100"),
        ]
    )
    def test_membership_rows_carry_parent_id(
        self, endpoint: str, parent_prefix: str, parent_column: str, child_path: str, limit: str | None
    ) -> None:
        # The same member sits under many parents, so each row must carry its parent id to keep
        # the composite primary key unique.
        parent_1, parent_2 = f"{parent_prefix}_1", f"{parent_prefix}_2"
        result = _driver().run(
            endpoint,
            [
                _page([{"id": parent_1}, {"id": parent_2}]),
                _page([{"id": "member_1"}]),
                _page([{"id": "member_1"}]),
            ],
        )

        assert result.raised is None
        assert result.response is not None
        primary_keys = result.response.primary_keys
        assert primary_keys is not None
        assert result.paths[1:] == [child_path.format(parent_1), child_path.format(parent_2)]
        assert result.params("limit")[1:] == [limit, limit]
        keys = [tuple(row[key] for key in primary_keys) for row in result.rows]
        assert keys == [(parent_1, "member_1"), (parent_2, "member_1")]

    def test_contact_list_contacts_follows_next_page_within_list(self) -> None:
        next_url = "https://api2.frontapp.com/contact_lists/grp_1/contacts?page_token=p2&limit=100"
        result = _driver().run(
            "contact_list_contacts",
            [
                _page([{"id": "grp_1"}]),
                _page([{"id": "crd_1"}], next_url),
                _page([{"id": "crd_2"}]),
            ],
        )

        assert [(row["contact_list_id"], row["id"]) for row in result.rows] == [("grp_1", "crd_1"), ("grp_1", "crd_2")]
        assert result.urls[2] == next_url


class TestFrontSourceResponse:
    @parameterized.expand(
        [
            ("events", "emitted_at", "week", "asc"),
            ("conversations", "created_at", "month", "asc"),
            ("accounts", "created_at", "month", "asc"),
            ("tags", "created_at", "month", "asc"),
            # Fan-out endpoints build their response down a separate branch.
            ("conversation_messages", "created_at", "month", "asc"),
            # Front returns comments newest-first and offers no sort param.
            ("conversation_comments", "posted_at", "month", "desc"),
        ]
    )
    def test_partitioned_endpoints(
        self, endpoint: str, partition_key: str, partition_format: str, sort_mode: str
    ) -> None:
        result = _driver().run(endpoint, [_page([])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.partition_format == partition_format
        assert response.sort_mode == sort_mode

    @parameterized.expand(
        [("contacts",), ("teammates",), ("inboxes",), ("channels",), ("teams",), ("contact_custom_fields",)]
    )
    def test_non_partitioned_endpoints(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
