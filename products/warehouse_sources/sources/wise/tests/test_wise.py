import gzip
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.sources.sdk import SourceCursorManager
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    activate_safe_point,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.sources.wise import wise
from products.warehouse_sources.sources.wise._config import WiseSourceConfig
from products.warehouse_sources.sources.wise.source import WiseSource
from products.warehouse_sources.sources.wise.wise import (
    FORBIDDEN_MESSAGE,
    INVALID_TOKEN_MESSAGE,
    STATEMENT_FORBIDDEN_MESSAGE,
    WiseResumeConfig,
    WiseStatementTooLargeError,
    format_wise_datetime,
    get_endpoint_permissions,
    validate_credentials,
)

PROFILES = [{"id": 101, "type": "BUSINESS"}, {"id": 202, "type": "PERSONAL"}]
INVALID_TOKEN_BODY = {"error": "invalid_token", "error_description": "Invalid token"}
STATEMENT_PATH = "/profiles/101/balance-statements/1/statement.json"
STATEMENT_BALANCE = {"id": 1, "currency": "EUR", "creationTime": "2024-03-15T00:00:00.000Z"}


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


@time_machine.travel("2024-05-01T00:00:00Z", tick=False)
def test_balance_statements_walk_past_empty_windows_and_keep_balance_keys() -> None:
    transaction = {"referenceNumber": "TRANSFER-1", "date": "2024-04-30T00:00:00.000Z", "type": "DEBIT"}
    result = driver().run(
        "balance_statements",
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES)],
                ("/profiles/101/balances", None): [
                    ScriptedResponse(json=[{**STATEMENT_BALANCE, "creationTime": "2023-01-01T00:00:00.000Z"}])
                ],
                (STATEMENT_PATH, None): [
                    ScriptedResponse(json={"transactions": []}),
                    ScriptedResponse(json={"transactions": [transaction]}),
                ],
                ("/profiles/202/balances", None): [
                    ScriptedResponse(json=[{"id": 1, "currency": "GBP", "creationTime": transaction["date"]}])
                ],
                ("/profiles/202/balance-statements/1/statement.json", None): [
                    ScriptedResponse(json={"transactions": [transaction]})
                ],
            }
        ),
    )

    assert result.raised is None
    assert result.committed_states[0].statement["next_intervals"][STATEMENT_PATH]["start"] == (
        "2024-04-13T23:59:59.999000+00:00"
    )
    statement_requests = [request for request in result.requests if request.path.endswith("/statement.json")]
    assert [request.param("currency") for request in statement_requests] == ["EUR", "EUR", "GBP"]
    assert [request.param("type") for request in statement_requests] == ["COMPACT"] * 3
    assert [request.param("intervalStart") for request in statement_requests] == [
        "2023-01-01T00:00:00.000Z",
        "2024-04-13T23:59:59.999Z",
        "2024-04-30T00:00:00.000Z",
    ]
    assert [request.param("intervalEnd") for request in statement_requests] == [
        "2024-04-14T00:00:00.000Z",
        "2024-05-01T00:00:00.000Z",
        "2024-05-01T00:00:00.000Z",
    ]
    assert result.rows == [{**transaction, "profileId": profile_id, "balanceId": 1} for profile_id in (101, 202)]


def test_balance_statements_can_stop_after_a_profile_with_no_balances() -> None:
    shutdown = RuntimeError("Worker shutdown")
    with scripted_network([ScriptedResponse(json=PROFILES), ScriptedResponse(json=[])]) as network:

        def stop_after_empty_balance() -> None:
            if len(network.requests_log) == 2:
                raise shutdown

        source = WiseSource()
        inputs = source_inputs("balance_statements")
        manager = source.get_resumable_source_manager(inputs)
        with (
            activate_safe_point(stop_after_empty_balance, covers_framework_checkpoints=False),
            pytest.raises(RuntimeError) as error,
        ):
            response = source.source_for_pipeline(WiseSourceConfig(api_token="wise-token"), manager, inputs)
            list(response.items())

    assert error.value is shutdown
    assert [request.path for request in network.requests_log] == ["/2026Q4/profiles", "/2026Q4/profiles/101/balances"]


@pytest.mark.parametrize(
    "oversized",
    [
        pytest.param(
            ScriptedResponse(
                body=gzip.compress(b'{"transactions":[],"padding":"' + b"x" * (256 * 1024) + b'"}'),
                headers={"Content-Encoding": "gzip"},
            ),
            id="decoded-body-over-limit",
        ),
        pytest.param(ScriptedResponse(status=413), id="http-413"),
    ],
)
@time_machine.travel("2024-05-01T00:00:00Z", tick=False)
def test_oversized_statement_window_splits_without_losing_or_repeating_rows(
    oversized: ScriptedResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wise, "MAX_STATEMENT_BYTES", 512)
    balance = {**STATEMENT_BALANCE, "creationTime": "2024-04-01T00:00:00.000Z"}
    boundary = {"referenceNumber": "TRANSFER-1", "date": "2024-04-16T00:00:00.000Z", "type": "DEBIT"}
    credit = {**boundary, "type": "CREDIT"}
    later = {**boundary, "date": "2024-04-17T00:00:00.000Z"}
    result = driver().run(
        "balance_statements",
        [
            ScriptedResponse(json=PROFILES[:1]),
            ScriptedResponse(json=[balance]),
            oversized,
            ScriptedResponse(json={"transactions": [boundary]}),
            ScriptedResponse(json={"transactions": [boundary, credit, later]}),
            ScriptedResponse(json={"transactions": []}),
        ],
    )

    assert result.raised is None
    assert result.params("intervalStart")[2:] == [
        "2024-04-01T00:00:00.000Z",
        "2024-04-01T00:00:00.000Z",
        "2024-04-15T23:59:59.999Z",
        "2024-04-30T23:59:59.998Z",
    ]
    assert result.params("intervalEnd")[2:] == [
        "2024-05-01T00:00:00.000Z",
        "2024-04-16T00:00:00.000Z",
        "2024-04-30T23:59:59.999Z",
        "2024-05-01T00:00:00.000Z",
    ]
    assert result.committed_states[0].statement["next_intervals"][STATEMENT_PATH]["start"] == (
        "2024-04-15T23:59:59.999000+00:00"
    )
    assert result.rows == [{**row, "profileId": 101, "balanceId": 1} for row in (boundary, credit, later)]


@time_machine.travel("2024-05-01T00:00:00Z", tick=False)
def test_oversized_statement_at_minimum_window_does_not_advance() -> None:
    result = driver().run(
        "balance_statements",
        [
            ScriptedResponse(json=PROFILES[:1]),
            ScriptedResponse(json=[{**STATEMENT_BALANCE, "creationTime": "2024-04-30T23:59:59.500Z"}]),
            ScriptedResponse(status=413),
        ],
    )

    assert isinstance(result.raised, WiseStatementTooLargeError)
    assert not result.committed_states


@pytest.mark.parametrize(
    "shifted,unshifted,expected_start",
    [
        (None, None, "2024-04-13T00:00:00.000Z"),
        ("2024-04-15T00:00:00Z", "2024-04-17T00:00:00Z", "2024-04-18T00:00:00.000Z"),
        ("2024-04-17T00:00:00Z", "2024-04-17T00:00:00Z", "2024-04-20T00:00:00.000Z"),
    ],
)
def test_balance_statements_use_each_balances_own_history(
    shifted: str | None, unshifted: str | None, expected_start: str
) -> None:
    source = WiseSource()
    inputs = source_inputs("balance_statements")
    first_cursor = SourceCursorManager.from_sync_type_config(source, None, inputs.logger)
    with time_machine.travel("2024-04-20T00:00:00Z", tick=False):
        first = driver().run(
            "balance_statements",
            [
                ScriptedResponse(json=PROFILES[:1]),
                ScriptedResponse(json=[STATEMENT_BALANCE]),
                ScriptedResponse(json={"transactions": []}),
            ],
            incremental_field="date",
            source_cursor=first_cursor,
        )
    assert first.raised is None
    payload = first_cursor.staged_payload()
    assert payload is not None
    next_cursor = SourceCursorManager.from_sync_type_config(source, {"source_cursor": payload}, inputs.logger)
    discovered = {**STATEMENT_BALANCE, "id": 2, "creationTime": "2024-03-01T00:00:00.000Z"}
    transaction = {"referenceNumber": "TRANSFER-1", "date": "2024-03-02T00:00:00.000Z", "type": "CREDIT"}
    with time_machine.travel("2024-05-01T00:00:00Z", tick=False):
        result = driver().run(
            "balance_statements",
            [
                ScriptedResponse(json=PROFILES[:1]),
                ScriptedResponse(json=[STATEMENT_BALANCE, discovered]),
                ScriptedResponse(json={"transactions": []}),
                ScriptedResponse(json={"transactions": [transaction]}),
            ],
            incremental_field="date",
            db_incremental_field_last_value=shifted,
            db_incremental_field_last_value_before_lookback=unshifted,
            source_cursor=next_cursor,
        )

    assert result.raised is None
    assert result.params("intervalStart") == [None, None, expected_start, "2024-03-01T00:00:00.000Z"]
    assert result.rows == [{**transaction, "profileId": 101, "balanceId": 2}]


@pytest.mark.parametrize("status,expected", [(401, INVALID_TOKEN_MESSAGE), (403, FORBIDDEN_MESSAGE)])
def test_balance_statement_permissions_distinguish_balance_list_denial(status: int, expected: str) -> None:
    with scripted_network([ScriptedResponse(json=PROFILES[:1]), ScriptedResponse(status=status)]):
        assert get_endpoint_permissions("wise-token", ["balance_statements"]) == {"balance_statements": expected}


def test_balance_statements_resume_at_the_next_window_with_the_original_end() -> None:
    balances = [
        {**STATEMENT_BALANCE, "id": 2, "creationTime": "2024-04-01T00:00:00.000Z"},
        {**STATEMENT_BALANCE, "creationTime": "2023-01-01T00:00:00.000Z"},
    ]
    boundary = {"referenceNumber": "TRANSFER-1", "date": "2024-04-14T00:00:00.000Z", "type": "DEBIT"}
    with time_machine.travel("2024-05-01T00:00:00Z", tick=False):
        first = driver().run(
            "balance_statements",
            responder(
                {
                    ("/profiles", None): [ScriptedResponse(json=PROFILES[:1])],
                    ("/profiles/101/balances", None): [ScriptedResponse(json=balances)],
                    ("/profiles/101/balance-statements/2/statement.json", None): [
                        ScriptedResponse(json={"transactions": [boundary]})
                    ],
                    (STATEMENT_PATH, None): [
                        ScriptedResponse(json={"transactions": [boundary]}),
                        ScriptedResponse(status=403, json={"error": "access_denied"}),
                    ],
                }
            ),
        )

    assert first.raised is not None
    assert [row["balanceId"] for row in first.rows] == [2, 1]
    later = {**boundary, "date": "2024-04-15T00:00:00.000Z", "type": "CREDIT"}
    with time_machine.travel("2024-05-02T00:00:00Z", tick=False):
        resumed = driver().run(
            "balance_statements",
            responder(
                {
                    ("/profiles", None): [ScriptedResponse(json=PROFILES[:1])],
                    ("/profiles/101/balances", None): [ScriptedResponse(json=list(reversed(balances)))],
                    (STATEMENT_PATH, None): [ScriptedResponse(json={"transactions": [boundary, later]})],
                }
            ),
            resume_state=first.committed_states[-1],
        )

    assert resumed.raised is None
    assert resumed.params("intervalStart") == [None, None, "2024-04-13T23:59:59.999Z"]
    assert resumed.params("intervalEnd") == [None, None, "2024-05-01T00:00:00.000Z"]
    assert resumed.rows == [{**later, "profileId": 101, "balanceId": 1}]


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


@time_machine.travel("2024-05-01T00:00:00Z", tick=False)
def test_balance_statement_permissions_probe_a_real_balance() -> None:
    with scripted_network(
        responder(
            {
                ("/profiles", None): [ScriptedResponse(json=PROFILES)],
                ("/profiles/101/balances", None): [ScriptedResponse(json=[STATEMENT_BALANCE])],
                (STATEMENT_PATH, None): [ScriptedResponse(status=403, json={"error": "access_denied"})],
            }
        ),
    ) as network:
        permissions = get_endpoint_permissions("wise-token", ["balance_statements"])

    assert permissions == {"balance_statements": STATEMENT_FORBIDDEN_MESSAGE}
    statement = network.requests_log[-1]
    assert statement.param("currency") == "EUR"
    assert statement.param("intervalStart") == "2024-04-30T00:00:00.000Z"
    assert statement.param("intervalEnd") == "2024-05-01T00:00:00.000Z"


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
