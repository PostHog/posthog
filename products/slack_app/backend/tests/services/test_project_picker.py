import json

import pytest

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.services.project_picker import (
    build_project_picker_blocks,
    pick_rejection,
    picked_integration_id,
)

MENTIONER = "U_ALICE"


def _candidate(integration_id: int, team_name: str = "Production") -> Integration:
    team = Team(id=integration_id, organization=Organization(name="Acme"), name=team_name)
    return Integration(id=integration_id, team=team, kind="slack", integration_id="T_WS")


def _click(element: dict, block_id: str) -> dict:
    action = {"action_id": element["action_id"], "block_id": block_id}
    if element["type"] == "static_select":
        action["selected_option"] = element["options"][-1]
    else:
        action["value"] = element["value"]
    return {"actions": [action]}


@pytest.mark.parametrize(
    "candidate_count, expected_element_type",
    [
        pytest.param(2, "button", id="few_projects_get_buttons"),
        pytest.param(6, "static_select", id="many_projects_get_a_dropdown"),
    ],
)
def test_every_choice_leads_back_to_its_project(candidate_count, expected_element_type):
    candidates = [_candidate(100 + index) for index in range(candidate_count)]

    blocks = build_project_picker_blocks(
        candidates, context_token="token-1", slack_user_id=MENTIONER, home_tab_url=None
    )

    actions_block = next(block for block in blocks if block["type"] == "actions")
    assert {element["type"] for element in actions_block["elements"]} == {expected_element_type}
    last_element = actions_block["elements"][-1]
    assert picked_integration_id(_click(last_element, actions_block["block_id"])) == candidates[-1].id


def test_long_project_name_stays_within_the_slack_text_limit():
    blocks = build_project_picker_blocks(
        [_candidate(1, team_name="x" * 200), _candidate(2)],
        context_token="token-1",
        slack_user_id=MENTIONER,
        home_tab_url=None,
    )

    actions_block = next(block for block in blocks if block["type"] == "actions")
    assert all(len(element["text"]["text"]) <= 75 for element in actions_block["elements"])


@pytest.mark.parametrize(
    "clicker, integration_id, expected",
    [
        pytest.param(MENTIONER, 101, None, id="the_mentioner_picks_a_listed_project"),
        pytest.param("U_BOB", 101, "not_the_mentioner", id="someone_else_clicks"),
        pytest.param(MENTIONER, 999, "not_a_candidate", id="project_was_not_offered"),
        pytest.param(MENTIONER, None, "not_a_candidate", id="click_names_no_project"),
    ],
)
def test_pick_is_accepted_only_from_the_mentioner_for_an_offered_project(clicker, integration_id, expected):
    context = {"slack_user_id": MENTIONER, "candidate_integration_ids": [101, 102]}

    assert pick_rejection(context, clicker_slack_user_id=clicker, integration_id=integration_id) == expected


def test_malformed_click_value_names_no_project():
    payload = {"actions": [{"action_id": "slack_app_project_picker_pick:101", "value": json.dumps([101])}]}

    assert picked_integration_id(payload) is None
