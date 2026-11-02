from datetime import UTC, datetime
from typing import Optional

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.clay.clay import (
    REQUEST_TIMEOUT_SECONDS,
    ClayResumeConfig,
    flatten_record,
    parse_table_ids,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clay.source import ClaySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clay import ClaySourceConfig

TABLE_ID = "t_0te9i4tZEHwc9hihBXu"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (TABLE_ID, [TABLE_ID]),
        (f"https://app.clay.com/workspaces/123/workbooks/wb_abc/tables/{TABLE_ID}/views/gv_xyz", [TABLE_ID]),
        (f"{TABLE_ID}, t_second\n  t_third\n{TABLE_ID}", [TABLE_ID, "t_second", "t_third"]),
        ("not a table id", []),
        ("", []),
    ],
)
def test_parse_table_ids(raw: str, expected: list[str]) -> None:
    assert parse_table_ids(raw) == expected


def test_flatten_record() -> None:
    record = {
        "Domain": {"status": "success", "value": "clay.com", "fields": None},
        "Enrich Company": {"status": "success", "value": "Clay", "fields": {"employee_count": 500}},
        "Work Email": {"status": "error", "error": "Provider request failed"},
        "Phone": {"status": "running"},
        "Notes": {"status": "empty"},
        "Owner_fields": {"status": "success", "value": "user column", "fields": None},
        "Owner": {"status": "success", "value": "Ada", "fields": {"title": "CEO"}},
    }

    assert flatten_record(record) == {
        "Domain": "clay.com",
        "Enrich Company": "Clay",
        "Enrich Company_fields": {"employee_count": 500},
        "Work Email": None,
        "Phone": None,
        "Notes": None,
        "Owner": "Ada",
        "Owner_fields": "user column",
    }


class TestClaySourceBehavior:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ClaySource(), ClaySourceConfig(api_key="clay_test_key", table_ids=TABLE_ID))

    def test_pages_with_body_cursor_and_saves_state(self) -> None:
        result = self._driver().run(
            TABLE_ID,
            [
                ScriptedResponse(
                    json={
                        "data": [{"Domain": {"status": "success", "value": "a.com", "fields": None}}],
                        "cursor": "c1",
                    }
                ),
                ScriptedResponse(json={"data": [{"Domain": {"status": "success", "value": "b.com", "fields": None}}]}),
            ],
        )

        assert result.raised is None
        sent_bodies = [request.json() for request in result.requests]
        assert [body.get("cursor") for body in sent_bodies] == [None, "c1"]
        assert all(
            body["query"] == {"tables": [{"id": TABLE_ID}], "field_mode": "names"} and body["limit"] == 100
            for body in sent_bodies
        )
        assert result.rows == [{"Domain": "a.com"}, {"Domain": "b.com"}]
        assert result.saved_states == [ClayResumeConfig(next_cursor="c1")]
        assert all(request.method == "POST" for request in result.requests)
        assert result.requests[0].headers["clay-api-key"] == "clay_test_key"
        assert all(request.read_timeout == REQUEST_TIMEOUT_SECONDS for request in result.requests)

    def test_resume_sends_saved_cursor_on_first_request(self) -> None:
        result = self._driver().run(
            TABLE_ID,
            [ScriptedResponse(json={"data": []})],
            resume_state=ClayResumeConfig(next_cursor="resumed"),
        )

        assert result.raised is None
        assert [request.json().get("cursor") for request in result.requests] == ["resumed"]

    @time_machine.travel("2026-03-04T05:06:07Z", tick=False)
    def test_credit_balances_reads_balance_endpoint_and_stamps_snapshot_time(self) -> None:
        result = self._driver().run(
            "credit_balances",
            [ScriptedResponse(json={"balance": 1250, "action_execution_balance": 300.5})],
        )

        assert result.raised is None
        assert [(request.method, request.path) for request in result.requests] == [
            ("GET", "/public/v0/credits/balance")
        ]
        assert result.requests[0].headers["clay-api-key"] == "clay_test_key"
        assert result.rows == [
            {
                "balance": 1250.0,
                "action_execution_balance": 300.5,
                "retrieved_at": datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
            }
        ]
        assert isinstance(result.rows[0]["balance"], float)


@pytest.mark.parametrize(
    ("me_status", "table_status", "expected_valid", "expected_message_part"),
    [
        (200, 200, True, None),
        (401, None, False, "rejected the API key"),
        (403, None, False, "while checking your API key"),
        # 429 and 5xx clear on their own, so waiting is a real next step. Every other 4xx fails
        # the same way on every attempt, so the copy names what the customer can change instead.
        (429, None, False, "Try again in a few minutes"),
        (500, None, False, "Try again in a few minutes"),
        (200, 403, False, "Enterprise plan"),
        (200, 404, False, "could not find table"),
        (200, 400, False, "Enable for API"),
        (200, 422, False, "Enable for API"),
        (200, 429, False, "Try again in a few minutes"),
        (200, 503, False, "Try again in a few minutes"),
    ],
)
def test_validate_credentials(
    me_status: int, table_status: Optional[int], expected_valid: bool, expected_message_part: Optional[str]
) -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/public/v0/me":
            return ScriptedResponse(status=me_status, json={})
        return ScriptedResponse(status=table_status or 200, json={"data": []})

    with scripted_network(respond):
        valid, message = validate_credentials("clay_test_key", [TABLE_ID])

    assert valid is expected_valid
    if expected_message_part is None:
        assert message is None
    else:
        assert message is not None and expected_message_part in message


def test_validate_credentials_requires_a_table_id() -> None:
    with scripted_network([]) as network:
        valid, message = validate_credentials("clay_test_key", [])

    assert valid is False
    assert message == "Enter at least one Clay table ID or table URL."
    assert network.session_options == []
    assert network.requests_log == []
