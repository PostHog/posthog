"""Unit tests for the notebook eval scorers.

Builds notebook documents in the shape the collab save stores — cell tags with their run
result written back — plus a synthetic churn needle, then asserts the score.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from unittest.mock import patch

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.notebooks.backend.models import Notebook, NotebookNodeRun
from products.notebooks.evals.scorers import CellRunsCompleted, ChurnCohortSurfaced
from products.notebooks.evals.seeders import seed_churn_signal
from products.notebooks.evals.synthesizer import CHURN_TOKEN, SIGNUP_EVENT, build_churn_needle
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

_ACCOUNTS: list[dict[str, Any]] = [
    {
        "index": account.index,
        "email": account.email,
        "name": account.name,
        "distinct_id": account.distinct_id,
        "account_key": account.account_key,
    }
    for account in build_churn_needle(count=3).accounts
]


def _sql_cell_listing(accounts: list[dict[str, Any]]) -> str:
    result = {
        "columns": ["email", "events"],
        "types": ["String", "UInt64"],
        "row_count": len(accounts),
        "first_page": [[account["email"], 120] for account in accounts],
        "has_more": False,
        "stdout": "",
        "stderr": "",
        "media": [],
    }
    code = json.dumps("SELECT properties.$email AS email, count() FROM events GROUP BY email")
    return (
        f'<SQLV2 nodeId="cell-1" title="Events per account" code={code} returnVariable="sql_df" '
        f'runId="run-1" result={{{json.dumps(result)}}} />'
    )


@pytest.mark.parametrize(
    "bodies,final_message,expected_score",
    [
        pytest.param([_sql_cell_listing(_ACCOUNTS)], "The analysis is in the notebook.", 0.0, id="run_rows_only"),
        pytest.param(
            [
                f"{_sql_cell_listing(_ACCOUNTS)}\n\n\n## Most at risk\n\n- {_ACCOUNTS[0]['email']}\n- {_ACCOUNTS[1]['name']}"
            ],
            "",
            2 / 3,
            id="prose_names_two",
        ),
        pytest.param([], f"Most at risk: {_ACCOUNTS[2]['distinct_id']}", 1 / 3, id="final_message_names_one"),
    ],
)
async def test_churn_cohort_surfaced_counts_prose_only(
    monkeypatch: pytest.MonkeyPatch, bodies: list[str], final_message: str, expected_score: float
) -> None:
    monkeypatch.setattr(ChurnCohortSurfaced, "_read_markdown_bodies", staticmethod(lambda team_id: bodies))
    output = {
        "seed": {"team_id": 1, "churn_needle": {"token": CHURN_TOKEN, "accounts": _ACCOUNTS}},
        "last_message": final_message,
    }

    score = await ChurnCohortSurfaced().eval_async(output, {"churn_cohort_surfaced": {}})

    assert score.score == pytest.approx(expected_score)


@pytest.mark.django_db
def test_read_runs_skips_soft_deleted_notebooks(team: Team) -> None:
    delivered = Notebook.objects.create(team=team, short_id="delivered")
    scratch = Notebook.objects.create(team=team, short_id="scratch", deleted=True)
    with team_scope(team.id):
        for notebook, node_type in (
            (scratch, NotebookNodeRun.NodeType.HOGQL),
            (scratch, NotebookNodeRun.NodeType.PYTHON),
            (delivered, NotebookNodeRun.NodeType.HOGQL),
        ):
            NotebookNodeRun.objects.create(
                team=team,
                notebook=notebook,
                node_id=f"{notebook.short_id}-{node_type}",
                node_type=node_type,
                status=NotebookNodeRun.Status.DONE,
            )

        runs = CellRunsCompleted._read_runs(team.id)

    assert [(run["notebook_short_id"], run["node_type"]) for run in runs] == [("delivered", "hogql")]


def test_churn_needle_plants_one_signup_before_every_session() -> None:
    signup, *sessions = build_churn_needle().schedule

    assert signup.event == SIGNUP_EVENT
    assert all(planted.days_before_now < signup.days_before_now for planted in sessions)
    assert all(planted.event != SIGNUP_EVENT for planted in sessions)


@pytest.mark.django_db
def test_planted_persons_are_last_seen_at_their_newest_event(team: Team) -> None:
    with (
        patch("products.notebooks.evals.seeders.create_person") as create_person,
        patch("products.notebooks.evals.seeders.create_person_distinct_id"),
        patch("products.notebooks.evals.seeders.bulk_create_events") as bulk_create_events,
        patch("products.notebooks.evals.seeders.raw_create_group_ch"),
        patch("products.notebooks.evals.seeders._seed_persons_db"),
    ):
        seed_churn_signal(CustomPromptSandboxContext(team_id=team.id, user_id=1))

    newest_event = max(event["timestamp"] for event in bulk_create_events.call_args.args[0])
    assert create_person.call_args_list
    assert all(call.kwargs["last_seen_at"] == newest_event for call in create_person.call_args_list)


@pytest.mark.parametrize(
    "expected,expected_score",
    [
        pytest.param({"churn_cohort_surfaced": {}}, 0.0, id="opted_in_without_a_seed"),
        pytest.param({}, None, id="not_requested"),
    ],
)
async def test_churn_cohort_surfaced_on_a_timed_out_case(
    expected: dict[str, Any], expected_score: float | None
) -> None:
    timed_out = {"exit_code": 1, "stderr": "case timeout after 900s"}

    score = await ChurnCohortSurfaced().eval_async(timed_out, expected)

    assert score.score == expected_score


@pytest.mark.django_db
def test_every_planted_account_key_gets_a_group_row(team: Team) -> None:
    with (
        patch("products.notebooks.evals.seeders.create_person"),
        patch("products.notebooks.evals.seeders.create_person_distinct_id"),
        patch("products.notebooks.evals.seeders.bulk_create_events") as bulk_create_events,
        patch("products.notebooks.evals.seeders.raw_create_group_ch") as raw_create_group_ch,
        patch("products.notebooks.evals.seeders._seed_persons_db"),
    ):
        seed_churn_signal(CustomPromptSandboxContext(team_id=team.id, user_id=1))

    event_keys = {
        event["properties"]["$group_0"]
        for event in bulk_create_events.call_args.args[0]
        if "$group_0" in event["properties"]
    }
    planted = {call.kwargs["group_key"]: call.kwargs["properties"] for call in raw_create_group_ch.call_args_list}

    assert event_keys and event_keys == set(planted)
    assert all(CHURN_TOKEN in properties["name"].lower() for properties in planted.values())


@pytest.mark.django_db
def test_planted_persons_reach_the_persons_database(team: Team) -> None:
    with (
        patch("products.notebooks.evals.seeders.create_person"),
        patch("products.notebooks.evals.seeders.create_person_distinct_id"),
        patch("products.notebooks.evals.seeders.bulk_create_events") as bulk_create_events,
        patch("products.notebooks.evals.seeders.raw_create_group_ch"),
        patch("products.notebooks.evals.seeders.persons_db_connection"),
        patch("products.notebooks.evals.seeders.insert_seed_person", return_value=1) as insert_seed_person,
        patch("products.notebooks.evals.seeders.insert_seed_distinct_id") as insert_seed_distinct_id,
    ):
        seed_churn_signal(CustomPromptSandboxContext(team_id=team.id, user_id=1))

    event_distinct_ids = {event["distinct_id"] for event in bulk_create_events.call_args.args[0]}
    seeded_distinct_ids = {call.kwargs["distinct_id"] for call in insert_seed_distinct_id.call_args_list}
    newest_event = max(event["timestamp"] for event in bulk_create_events.call_args.args[0])

    assert event_distinct_ids and seeded_distinct_ids == event_distinct_ids
    assert all(call.kwargs["last_seen_at"] == newest_event for call in insert_seed_person.call_args_list)
