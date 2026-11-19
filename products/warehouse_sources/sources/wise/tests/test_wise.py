from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.sources.wise._config import WiseSourceConfig
from products.warehouse_sources.sources.wise.source import WiseSource
from products.warehouse_sources.sources.wise.wise import (
    FORBIDDEN_MESSAGE,
    INVALID_TOKEN_MESSAGE,
    WiseResumeConfig,
    format_wise_datetime,
    get_endpoint_permissions,
    validate_credentials,
)

PROFILES = [{"id": 101, "type": "BUSINESS"}, {"id": 202, "type": "PERSONAL"}]
INVALID_TOKEN_BODY = {"error": "invalid_token", "error_description": "Invalid token"}


def driver() -> SourceDriver:
    return SourceDriver(WiseSource(), WiseSourceConfig(api_token="wise-token"))


def responder(answers: dict[tuple[str, str | None], list[ScriptedResponse]]):
    # Every profile's transfers share one path, so the answer is picked by path and profile.
    def respond(request: RecordedRequest) -> ScriptedResponse:
        path = request.path.removeprefix("/2026Q4")
        profile = request.param("profile") or request.param("profileId")
        queue = answers.get((path, profile)) or answers.get((path, None))
        assert queue, f"unexpected request {request.url}"
        return queue.pop(0)

    return respond


def transfer_rows(start: int, count: int) -> list[dict[str, Any]]:
    return [{"id": start + i, "created": "2024-05-01 10:00:00"} for i in range(count)]


def test_transfers_walk_offset_pages_for_every_profile() -> None:
    result = driver().run(
        "transfers",
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES)],
                ("/transfers", "101"): [
                    ScriptedResponse(json=transfer_rows(0, 100)),
                    ScriptedResponse(json=transfer_rows(100, 1)),
                ],
                ("/transfers", "202"): [ScriptedResponse(json=[])],
            }
        ),
        incremental_field=None,
    )

    assert result.raised is None
    assert result.paths == ["/2026Q4/profiles", "/2026Q4/transfers", "/2026Q4/transfers", "/2026Q4/transfers"]
    assert result.params("profile") == [None, "101", "101", "202"]
    assert result.params("offset") == [None, "0", "100", "0"]
    assert result.params("limit") == [None, "100", "100", "100"]
    assert len(result.rows) == 101
    assert {row["profileId"] for row in result.rows} == {101}
    assert all(request.headers["authorization"] == "Bearer wise-token" for request in result.requests)


@pytest.mark.parametrize(
    "schema,filter_param,child_path,page,watermark,expected_filter",
    [
        ("transfers", "createdDateStart", "/transfers", [], None, None),
        (
            "transfers",
            "createdDateStart",
            "/transfers",
            [],
            datetime(2024, 5, 1, 10, 0, 0, 123000, tzinfo=UTC),
            "2024-05-01T10:00:00.123Z",
        ),
        (
            "activities",
            "since",
            "/profiles/101/activities",
            {"cursor": None, "activities": []},
            "2024-05-01T10:00:00.000Z",
            "2024-05-01T10:00:00.000Z",
        ),
        ("activities", "since", "/profiles/101/activities", {"cursor": None, "activities": []}, None, None),
    ],
)
def test_incremental_filter_is_sent_only_once_a_watermark_exists(
    schema: str, filter_param: str, child_path: str, page: Any, watermark: Any, expected_filter: str | None
) -> None:
    result = driver().run(
        schema,
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES[:1])],
                (child_path, None): [ScriptedResponse(json=page)],
            }
        ),
        incremental_field="created" if schema == "transfers" else "createdOn",
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.params(filter_param)[1:] == [expected_filter]


def test_full_refresh_sends_no_incremental_filter() -> None:
    result = driver().run(
        "transfers",
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES[:1])],
                ("/transfers", None): [ScriptedResponse(json=[])],
            }
        ),
        incremental_field="created",
        should_use_incremental_field=False,
        db_incremental_field_last_value="2024-05-01T10:00:00.000Z",
    )

    assert result.raised is None
    assert result.params("createdDateStart") == [None, None]


@pytest.mark.parametrize(
    "schema,child_path,data_key,cursor_key,cursor_param,size,pages,expected_cursors",
    [
        (
            # A last page that still carries a seek position ends on the next, empty page.
            "recipients",
            "/accounts",
            "content",
            "seekPositionForNext",
            "seekPosition",
            "20",
            [([{"id": 1, "profileId": 101}], 55), ([{"id": 2, "profileId": 101}], 77), ([], 99)],
            [None, "55", "77"],
        ),
        (
            "activities",
            "/profiles/101/activities",
            "activities",
            "cursor",
            "nextCursor",
            "100",
            [([{"id": "a1", "createdOn": "2024-01-01T00:00:00Z"}], "c2"), ([{"id": "a2"}], None)],
            [None, "c2"],
        ),
    ],
)
def test_cursor_tables_follow_the_cursor_to_the_last_page(
    schema: str,
    child_path: str,
    data_key: str,
    cursor_key: str,
    cursor_param: str,
    size: str,
    pages: list[tuple[list[dict[str, Any]], Any]],
    expected_cursors: list[str | None],
) -> None:
    result = driver().run(
        schema,
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES[:1])],
                (child_path, None): [
                    ScriptedResponse(json={data_key: rows, cursor_key: cursor}) for rows, cursor in pages
                ],
            }
        ),
    )

    assert result.raised is None
    assert result.params(cursor_param)[1:] == expected_cursors
    assert result.params("size")[1:] == [size] * len(expected_cursors)
    assert [row["profileId"] for row in result.rows] == [101] * (len(pages) - (1 if schema == "recipients" else 0))


def test_balances_request_both_balance_types_and_carry_the_profile_id() -> None:
    result = driver().run(
        "balances",
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES)],
                ("/profiles/101/balances", None): [ScriptedResponse(json=[{"id": 1, "currency": "EUR"}])],
                ("/profiles/202/balances", None): [ScriptedResponse(json=[{"id": 1, "currency": "GBP"}])],
            }
        ),
    )

    assert result.raised is None
    assert result.params("types")[1:] == ["STANDARD,SAVINGS", "STANDARD,SAVINGS"]
    assert [(row["profileId"], row["id"]) for row in result.rows] == [(101, 1), (202, 1)]


def test_transfers_stage_the_next_offset_and_resume_from_it() -> None:
    first = driver().run(
        "transfers",
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES[:1])],
                ("/transfers", "101"): [
                    ScriptedResponse(json=transfer_rows(0, 100)),
                    ScriptedResponse(json=transfer_rows(100, 1)),
                ],
            }
        ),
    )
    in_progress = WiseResumeConfig(
        paginator_state={"completed": [], "current": "/transfers?profile=101", "child_state": {"offset": 100}}
    )
    assert in_progress in first.committed_states

    resumed = driver().run(
        "transfers",
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES)],
                ("/transfers", "101"): [ScriptedResponse(json=transfer_rows(100, 1))],
                ("/transfers", "202"): [ScriptedResponse(json=[])],
            }
        ),
        resume_state=in_progress,
    )

    assert resumed.raised is None
    assert resumed.params("offset")[1:] == ["100", "0"]
    assert [row["id"] for row in resumed.rows] == [100]


@pytest.mark.parametrize(
    "answer,expected",
    [
        (ScriptedResponse(json=PROFILES), (True, None)),
        (ScriptedResponse(status=401, json=INVALID_TOKEN_BODY), (False, INVALID_TOKEN_MESSAGE)),
        (ScriptedResponse(status=403, json={"error": "access_denied"}), (False, FORBIDDEN_MESSAGE)),
        (ScriptedResponse(status=404, json={}), (False, "Wise returned an unexpected response (HTTP 404).")),
    ],
)
def test_validate_credentials_maps_the_profiles_probe(answer: ScriptedResponse, expected: tuple) -> None:
    with scripted_network([answer]) as network:
        assert validate_credentials("wise-token") == expected

    assert network.requests_log[0].url == "https://api.wise.com/2026Q4/profiles"


def test_endpoint_permissions_probe_each_table_with_the_first_profile() -> None:
    with scripted_network(
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES)],
                ("/profiles/101/balances", None): [ScriptedResponse(json=[])],
                ("/transfers", "101"): [ScriptedResponse(json=[])],
                ("/accounts", "101"): [ScriptedResponse(status=403, json={"error": "access_denied"})],
                ("/profiles/101/activities", None): [ScriptedResponse(status=401, json=INVALID_TOKEN_BODY)],
            }
        )
    ) as network:
        permissions = get_endpoint_permissions(
            "wise-token", ["profiles", "balances", "transfers", "recipients", "activities"]
        )

    assert permissions == {
        "profiles": None,
        "balances": None,
        "transfers": None,
        "recipients": FORBIDDEN_MESSAGE,
        "activities": FORBIDDEN_MESSAGE,
    }
    transfers_probe = next(request for request in network.requests_log if request.path.endswith("/transfers"))
    assert (transfers_probe.param("profile"), transfers_probe.param("limit")) == ("101", "1")


@pytest.mark.parametrize(
    "value,expected",
    [
        (datetime(2024, 5, 1, 12, 0, 0, 123456, tzinfo=UTC), "2024-05-01T12:00:00.123Z"),
        (datetime(2024, 5, 1, 12, 0, 0), "2024-05-01T12:00:00.000Z"),
        ("2017-03-14 15:25:51", "2017-03-14T15:25:51.000Z"),
        ("2024-05-01T12:00:00.000Z", "2024-05-01T12:00:00.000Z"),
        (None, None),
    ],
)
def test_format_wise_datetime(value: Any, expected: str | None) -> None:
    assert format_wise_datetime(value) == expected
