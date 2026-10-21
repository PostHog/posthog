from collections.abc import Iterator
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.arcade import (
    ArcadeResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.settings import (
    INSIGHTS_ERROR,
    PERMISSION_ERROR,
    PROVISIONING_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.source import ArcadeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.arcade import ArcadeSourceConfig


@pytest.fixture
def config() -> ArcadeSourceConfig:
    return ArcadeSourceConfig(api_key="fake-arcade-key", team_id="team-example", start_date="2025-01-01")


@pytest.fixture(autouse=True)
def fixed_time() -> Iterator[None]:
    with time_machine.travel("2025-02-01T00:00:00Z", tick=False):
        yield


@pytest.mark.parametrize("resume_page", [None, 3])
def test_flow_pages_and_resume(config: ArcadeSourceConfig, resume_page: int | None) -> None:
    resume_state = (
        ArcadeResumeConfig(
            page=resume_page, period_start="2025-01-01T00:00:00+00:00", period_end="2025-01-31T00:00:00+00:00"
        )
        if resume_page
        else None
    )
    result = SourceDriver(ArcadeSource(), config).run(
        "flow_engagement",
        [
            ScriptedResponse(json=[{"flowId": "flow-one", "plays": 7}]),
            ScriptedResponse(json=[{"flowId": "flow-two", "plays": 9}]),
            ScriptedResponse(json=[]),
        ],
        resume_state=resume_state,
    )

    assert result.raised is None
    assert [row["flowId"] for row in result.rows] == ["flow-one", "flow-two"]
    assert all(row["team_id"] == "team-example" for row in result.rows)
    start_page = resume_page or 1
    expected_end = "2025-01-31T00:00:00+00:00" if resume_page else "2025-02-01T00:00:00+00:00"
    assert [request.json()["page"] for request in result.requests] == list(range(start_page, start_page + 3))
    for request in result.requests:
        assert request.method == "POST"
        assert request.url == "https://api.arcade.software/insights"
        assert request.headers["authorization"] == "fake-arcade-key"
        assert request.json() == {
            "type": "overviewPlays",
            "teamId": "team-example",
            "page": request.json()["page"],
            "size": 100,
            "from": "2025-01-01T00:00:00+00:00",
            "to": expected_end,
        }
    assert result.rows[0]["period_end"] == expected_end
    assert result.saved_states[0].page == start_page + 1
    assert result.committed_states[0].page == start_page + 1
    assert result.saved_states[-1].completed


@pytest.mark.parametrize(
    ("name", "payload", "expected_rows", "method", "path", "expected_body"),
    [
        ("teams", {"success": True, "teams": [{"id": "team-one"}]}, [{"id": "team-one"}], "GET", "teams", None),
        ("users", {"success": True, "users": []}, [], "GET", "users", None),
        (
            "company_leads",
            [{"id": "company-one", "last7d": 5}],
            [{"id": "company-one", "last7d": 5, "team_id": "team-example"}],
            "POST",
            "insights",
            {"type": "companiesForLeads", "teamId": "team-example"},
        ),
        (
            "total_plays",
            {"players": 12, "plays": 20},
            [
                {
                    "players": 12,
                    "plays": 20,
                    "team_id": "team-example",
                    "period_start": "2025-01-01T00:00:00+00:00",
                    "period_end": "2025-02-01T00:00:00+00:00",
                }
            ],
            "POST",
            "insights",
            {
                "type": "totalPlays",
                "teamId": "team-example",
                "from": "2025-01-01T00:00:00+00:00",
                "to": "2025-02-01T00:00:00+00:00",
            },
        ),
    ],
)
def test_single_page_tables(
    config: ArcadeSourceConfig,
    name: str,
    payload: object,
    expected_rows: list[dict[str, Any]],
    method: str,
    path: str,
    expected_body: dict[str, str] | None,
) -> None:
    result = SourceDriver(ArcadeSource(), config).run(name, [ScriptedResponse(json=payload)])

    assert result.raised is None
    assert result.rows == expected_rows
    assert len(result.requests) == 1
    request = result.requests[0]
    assert request.method == method
    assert request.url == f"https://api.arcade.software/{path}"
    assert request.headers["authorization"] == "fake-arcade-key"
    assert request.json() == expected_body
    assert result.saved_states[-1].completed


@pytest.mark.parametrize(
    ("name", "insight_type", "answers", "expected_rows"),
    [
        (
            "flow_views",
            "views",
            [{"viewers": 4}, {"viewers": 6}],
            [{"viewers": 4, "flowId": "flow-one"}, {"viewers": 6, "flowId": "flow-two"}],
        ),
        (
            "flow_dropoff",
            "dropoff",
            [[{"stepId": "step-a", "reached": 5}], []],
            [{"stepId": "step-a", "reached": 5, "flowId": "flow-one"}],
        ),
        (
            "authenticated_views",
            "authenticatedViews",
            [[], [{"email": "viewer@example.com", "completed": True}]],
            [{"email": "viewer@example.com", "completed": True, "flowId": "flow-two"}],
        ),
    ],
)
@pytest.mark.parametrize("resume_index", [None, 1])
def test_per_flow_tables_fan_out_over_flows(
    config: ArcadeSourceConfig,
    name: str,
    insight_type: str,
    answers: list[object],
    expected_rows: list[dict[str, Any]],
    resume_index: int | None,
) -> None:
    resume_state = (
        ArcadeResumeConfig(
            page=1,
            period_start="2025-01-01T00:00:00+00:00",
            period_end="2025-02-01T00:00:00+00:00",
            flow_index=resume_index,
        )
        if resume_index
        else None
    )
    flow_answers = answers[resume_index or 0 :]
    result = SourceDriver(ArcadeSource(), config).run(
        name,
        [
            ScriptedResponse(json=[{"flowId": "flow-one"}, {"flowId": "flow-two"}]),
            *(ScriptedResponse(json=answer) for answer in flow_answers),
            ScriptedResponse(json=[]),
        ],
        resume_state=resume_state,
    )

    assert result.raised is None
    expected_flows = ["flow-one", "flow-two"][resume_index or 0 :]
    assert result.rows == [
        {
            **row,
            "team_id": "team-example",
            "period_start": "2025-01-01T00:00:00+00:00",
            "period_end": "2025-02-01T00:00:00+00:00",
        }
        for row in expected_rows
        if row["flowId"] in expected_flows
    ]
    bodies = [request.json() for request in result.requests]
    assert [body["type"] for body in bodies] == [
        "overviewPlays",
        *[insight_type] * len(expected_flows),
        "overviewPlays",
    ]
    assert [body["page"] for body in (bodies[0], bodies[-1])] == [1, 2]
    for body, flow_id in zip(bodies[1:-1], expected_flows):
        assert body == {
            "type": insight_type,
            "teamId": "team-example",
            "flowId": flow_id,
            "from": "2025-01-01T00:00:00+00:00",
            "to": "2025-02-01T00:00:00+00:00",
        }
    assert [state.flow_index for state in result.saved_states[:-1]] == [1, 2][resume_index or 0 :]
    assert result.saved_states[-1].completed


@pytest.mark.parametrize("name", ["teams", "flow_engagement", "flow_views"])
def test_completed_resume_does_not_repeat_rows(config: ArcadeSourceConfig, name: str) -> None:
    result = SourceDriver(ArcadeSource(), config).run(
        name,
        [],
        resume_state=ArcadeResumeConfig(
            page=1, period_start="2025-01-01T00:00:00+00:00", period_end="2025-01-31T00:00:00+00:00", completed=True
        ),
    )

    assert result.raised is None
    assert result.items == []
    assert result.requests == []


@pytest.mark.parametrize(
    ("status", "error", "message"),
    [
        (403, "This operation requires provisioning scope", PROVISIONING_ERROR),
        (403, "This operation requires insights scope", INSIGHTS_ERROR),
        (403, "Forbidden", PERMISSION_ERROR),
    ],
)
def test_auth_error_mapping(config: ArcadeSourceConfig, status: int, error: str, message: str) -> None:
    answer = ScriptedResponse(status=status, json={"error": error})
    with scripted_network([answer]) as network:
        assert validate_credentials(config, 1, "teams") == (False, message)
    assert len(network.requests_log) == 1

    result = SourceDriver(ArcadeSource(), config).run("teams", [answer])
    assert isinstance(result.raised, ValueError)
    assert str(result.raised) == message
    assert ArcadeSource().get_non_retryable_errors()[str(result.raised)] == message
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_create_accepts_missing_scope(config: ArcadeSourceConfig, status: int) -> None:
    with scripted_network(
        [ScriptedResponse(status=status, json={"error": "This operation requires provisioning scope"})]
    ) as network:
        valid, _ = validate_credentials(config, 1, None)

    assert valid == (status == 403)
    assert len(network.requests_log) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_retry(config: ArcadeSourceConfig, status: int) -> None:
    result = SourceDriver(ArcadeSource(), config).run(
        "teams",
        [ScriptedResponse(status=status, json={"error": "Temporary failure"}), ScriptedResponse(json={"teams": []})],
    )

    assert result.raised is None
    assert result.rows == []
    assert len(result.requests) == 2


@pytest.mark.parametrize("start_date", ["not-a-date", "2025-02-30", "2026-01-01"])
def test_invalid_dates_do_not_send_requests(config: ArcadeSourceConfig, start_date: str) -> None:
    config.start_date = start_date
    with scripted_network([]) as network:
        valid, message = validate_credentials(config, 1, None)

    assert not valid
    assert message and "date" in message
    assert network.requests_log == []


def test_unknown_table_does_not_send_requests(config: ArcadeSourceConfig) -> None:
    with scripted_network([]) as network:
        assert validate_credentials(config, 1, "unknown")[0] is False
    result = SourceDriver(ArcadeSource(), config).run("unknown", [])

    assert isinstance(result.raised, ValueError)
    assert "Unknown Arcade table" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


@pytest.mark.parametrize("name", ["flow_engagement", "flow_views"])
def test_validation_uses_one_small_insights_page(config: ArcadeSourceConfig, name: str) -> None:
    with scripted_network([ScriptedResponse(json=[{"flowId": "flow-one"}])]) as network:
        assert validate_credentials(config, 1, name) == (True, None)

    assert len(network.requests_log) == 1
    assert network.requests_log[0].json()["type"] == "overviewPlays"
    assert network.requests_log[0].json()["size"] == 1


def test_missing_list_fails_instead_of_deleting_rows(config: ArcadeSourceConfig) -> None:
    result = SourceDriver(ArcadeSource(), config).run("teams", [ScriptedResponse(json={"unexpected": []})])

    assert isinstance(result.raised, ValueError)
    assert result.saved_states == []
