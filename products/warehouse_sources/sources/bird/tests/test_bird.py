from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.sources.bird._config import BirdSourceConfig
from products.warehouse_sources.sources.bird.bird import (
    INVALID_KEY_ERROR,
    INVALID_KEY_FORMAT_ERROR,
    UNVERIFIED_KEY_ERROR,
    WRONG_REGION_ERROR,
    BirdResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.sources.bird.source import BirdSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network

US_KEY = "bk_us1_testkey123"


def _driver(api_key: str = US_KEY) -> SourceDriver:
    return SourceDriver(BirdSource(), BirdSourceConfig(api_key=api_key))


def _page(ids: list[str], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": [{"id": row_id, "created_at": "2026-11-01T10:00:00Z"} for row_id in ids],
            "next_cursor": next_cursor,
            "prev_cursor": None,
            "refresh_cursor": "refresh" if ids else None,
        }
    )


def _error(status: int, error_type: str, code: str) -> ScriptedResponse:
    return ScriptedResponse(
        status=status,
        json={"error": {"type": error_type, "code": code, "message": "error", "request_id": "req_test"}},
    )


class TestCursorListings:
    @pytest.mark.parametrize(
        ("api_key", "origin"),
        [
            ("bk_us1_testkey123", "https://us1.platform.bird.com"),
            ("bk_eu1_testkey123", "https://eu1.platform.bird.com"),
        ],
    )
    def test_walks_next_cursor_to_the_last_page_on_the_key_region(self, api_key: str, origin: str) -> None:
        result = _driver(api_key).run(
            "contacts",
            [_page(["c1", "c2"], "cur_a"), _page(["c3"], "cur_b"), _page(["c4"], None)],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c1", "c2", "c3", "c4"]
        assert {request.origin for request in result.requests} == {origin}
        assert {request.headers["authorization"] for request in result.requests} == {f"Bearer {api_key}"}
        assert result.params("starting_after") == [None, "cur_a", "cur_b"]
        assert result.params("limit") == ["100", "100", "100"]
        assert result.saved_states == [
            BirdResumeConfig(starting_after="cur_a"),
            BirdResumeConfig(starting_after="cur_b"),
        ]

    def test_a_repeated_cursor_fails_instead_of_looping(self) -> None:
        result = _driver().run("audiences", [_page(["a1"], "cur_a"), _page(["a2"], "cur_a")])

        assert result.raised is not None
        assert result.params("starting_after") == [None, "cur_a"]

    def test_resume_starts_from_the_saved_cursor(self) -> None:
        result = _driver().run(
            "email_messages",
            [_page(["em_9"], None)],
            resume_state=BirdResumeConfig(starting_after="cur_saved"),
        )

        assert result.raised is None
        assert result.params("starting_after") == ["cur_saved"]
        assert [row["id"] for row in result.rows] == ["em_9"]

    def test_a_response_without_data_fails_the_run(self) -> None:
        result = _driver().run("numbers", [ScriptedResponse(json={"items": [{"id": "n1"}]})])

        assert result.raised is not None
        assert result.rows == []

    def test_a_key_without_a_region_prefix_stays_on_a_bird_host(self) -> None:
        result = _driver("evil.example.com/x").run("contacts", [_page(["c1"], None)])

        assert result.raised is None
        assert {request.origin for request in result.requests} == {"https://us1.platform.bird.com"}


class TestIncremental:
    @pytest.mark.parametrize(
        ("schema", "inputs", "expected"),
        [
            (
                "email_inbound_messages",
                {
                    "should_use_incremental_field": True,
                    "db_incremental_field_last_value": datetime(2026, 11, 2, 8, 30, tzinfo=UTC),
                },
                {"received_after": "2026-11-02T08:30:00Z"},
            ),
            (
                "email_inbound_messages",
                {
                    "should_use_incremental_field": True,
                    "db_incremental_field_last_value": datetime(2026, 11, 2, 8, 30),
                },
                {"received_after": "2026-11-02T08:30:00Z"},
            ),
            # The first incremental sync has no watermark yet and reads everything Bird keeps.
            (
                "email_inbound_messages",
                {"should_use_incremental_field": True, "db_incremental_field_last_value": None},
                {"received_after": None},
            ),
            (
                "email_inbound_messages",
                {
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": datetime(2026, 11, 2, tzinfo=UTC),
                },
                {"received_after": None},
            ),
            # Message status changes after creation, so a created-time watermark must never filter it.
            (
                "email_messages",
                {
                    "should_use_incremental_field": True,
                    "db_incremental_field_last_value": datetime(2026, 11, 2, tzinfo=UTC),
                },
                {"created_after": None},
            ),
            (
                "sms_messages",
                {
                    "should_use_incremental_field": True,
                    "db_incremental_field_last_value": datetime(2026, 11, 2, tzinfo=UTC),
                },
                {"created_after": None},
            ),
        ],
    )
    def test_shapes_the_time_filter(self, schema: str, inputs: dict[str, Any], expected: dict[str, str | None]) -> None:
        result = _driver().run(schema, [_page(["r1"], None)], **inputs)

        assert result.raised is None
        for param, value in expected.items():
            assert result.params(param) == [value]


class TestDailyStats:
    @pytest.mark.parametrize("schema", ["email_daily_stats", "sms_daily_stats", "whatsapp_daily_stats"])
    def test_requests_the_last_365_days_in_one_page_without_cursor_params(self, schema: str) -> None:
        stats = ScriptedResponse(
            json={
                "period": {"from": "2025-11-14", "to": "2026-11-13"},
                "data": [{"bucket": "2026-11-12", "delivery": {}}, {"bucket": "2026-11-13", "delivery": {}}],
            }
        )

        with time_machine.travel(datetime(2026, 11, 13, 23, 0, tzinfo=UTC), tick=False):
            result = _driver().run(schema, [stats])

        assert result.raised is None
        assert [row["bucket"] for row in result.rows] == ["2026-11-12", "2026-11-13"]
        # Bird rejects unknown query parameters and windows over 365 days with a 422.
        assert result.queries == [{"from": ("2025-11-14",), "to": ("2026-11-13",)}]
        assert result.response is not None
        assert result.response.primary_keys == ["bucket"]


class TestErrors:
    @pytest.mark.parametrize(
        ("answer", "expected_message"),
        [
            (_error(401, "auth_error", "E02001"), INVALID_KEY_ERROR),
            (_error(403, "permission_error", "E02002"), "can't read one of the tables you sync"),
        ],
    )
    def test_auth_failures_match_a_non_retryable_error(self, answer: ScriptedResponse, expected_message: str) -> None:
        result = _driver().run("contacts", [answer])

        assert result.raised is not None
        raised = str(result.raised)
        matches = [message for key, message in BirdSource().get_non_retryable_errors().items() if key in raised]
        assert len(matches) == 1
        assert matches[0] is not None and expected_message in matches[0]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("answer", "schema_name", "expected"),
        [
            (_page([], None), None, (True, None)),
            (_error(401, "auth_error", "E02001"), None, (False, INVALID_KEY_ERROR)),
            # A genuine key may lack the scope of one table, which must not block creating the source.
            (_error(403, "permission_error", "E02002"), None, (True, None)),
            (_error(421, "misdirected_error", "E01010"), None, (False, WRONG_REGION_ERROR)),
            (_error(500, "internal_error", "E01000"), None, (False, UNVERIFIED_KEY_ERROR)),
        ],
    )
    def test_maps_the_probe_response(
        self, answer: ScriptedResponse, schema_name: str | None, expected: tuple[bool, str | None]
    ) -> None:
        with scripted_network(always(answer)) as network:
            assert validate_credentials(US_KEY, schema_name) == expected

        assert {request.url for request in network.requests_log} == {
            "https://us1.platform.bird.com/v1/contacts?limit=1"
        }
        assert {request.headers["authorization"] for request in network.requests_log} == {f"Bearer {US_KEY}"}

    @pytest.mark.parametrize(
        ("schema_name", "url"),
        [
            ("sms_messages", "https://us1.platform.bird.com/v1/sms/messages?limit=1"),
            ("whatsapp_daily_stats", "https://us1.platform.bird.com/v1/whatsapp/stats/daily"),
        ],
    )
    def test_a_table_without_its_scope_fails_only_that_table(self, schema_name: str, url: str) -> None:
        with scripted_network(always(_error(403, "permission_error", "E02002"))) as network:
            valid, message = validate_credentials(US_KEY, schema_name)

        assert valid is False
        assert message is not None and schema_name in message
        assert [request.url for request in network.requests_log] == [url]

    @pytest.mark.parametrize(
        "api_key",
        [
            "AccessKey abc123",
            "bk_us1",
            # The region becomes part of the host name, so anything but a region code stays on us1.
            "bk_evil.example.com/x_abc",
            "bk_US1_abc",
        ],
    )
    def test_a_rejected_key_without_a_region_prefix_explains_the_key_format(self, api_key: str) -> None:
        with scripted_network(always(_error(401, "auth_error", "E02001"))) as network:
            assert validate_credentials(api_key) == (False, INVALID_KEY_FORMAT_ERROR)

        assert [request.origin for request in network.requests_log] == ["https://us1.platform.bird.com"]
