from typing import Any

import pytest
from unittest.mock import patch

from posthog.models import Organization, OrganizationMembership
from posthog.models.integration import Integration

from products.slack_app.backend.logic.onboarding.actions import CONTINUE_ACTION_ID, SKIP_ACTION_ID
from products.slack_app.backend.logic.onboarding.card import plan_onboarding
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStep, read_action_value
from products.slack_app.backend.logic.onboarding.steps import ONBOARDING_STEPS
from products.slack_app.backend.services.workspace_integrations import (
    WorkspaceIntegration,
    require_workspace_integration,
)
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID

GITHUB_STEP = "products.slack_app.backend.logic.onboarding.github_step"
ADMIN_SCOPES = "chat:write,users:read,users:read.email,channels:manage,channels:read,groups:read"


def _install(team, *, installer: str | None = None) -> WorkspaceIntegration:
    config: dict[str, Any] = {"scope": ADMIN_SCOPES}
    if installer:
        config["authed_user"] = {"id": installer}
    row = Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=SLACK_TEAM_ID,
        config=config,
        sensitive_config={"access_token": "xoxb-test"},
    )
    return require_workspace_integration(row.id, SLACK_TEAM_ID)


def _clickable(blocks: list[dict]) -> list[dict[str, Any]]:
    # Each clickable element, shaped like the action Slack sends back when someone clicks it.
    actions = []
    for block in blocks:
        for element in block.get("elements") or []:
            if "action_id" not in element:
                continue
            option = (element.get("options") or [None])[0]
            actions.append(
                {
                    "action_id": element["action_id"],
                    "block_id": block.get("block_id"),
                    "value": element.get("value"),
                    "selected_option": option,
                    "selected_options": [option] if option else [],
                }
            )
    return actions


@pytest.mark.django_db
@pytest.mark.parametrize("step", ONBOARDING_STEPS, ids=lambda step: step.key)
def test_each_button_on_a_step_reaches_a_handler(step: OnboardingStep, org_team_user, link_user) -> None:
    org, team, user = org_team_user
    OrganizationMembership.objects.filter(user=user, organization=org).update(level=OrganizationMembership.Level.ADMIN)
    link_user(user)
    integration = _install(team)
    ctx = OnboardingContext(integration=integration, slack_user_id=SLACK_USER_ID)

    clicked = _clickable(step.render(ctx))

    assert (SKIP_ACTION_ID in [action["action_id"] for action in clicked]) is step.skippable
    for action in clicked:
        if action["action_id"] in (SKIP_ACTION_ID, CONTINUE_ACTION_ID):
            value = read_action_value(action)
            assert value is not None and value["step"] == step.key
        else:
            assert step.handles(action["action_id"])
            value = step.read_value(action)
        assert value is not None and value["integration_id"] == integration.id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role, expected",
    [
        ("member", ["link_account", "model", "replies_in_threads"]),
        ("member_with_team_github", ["link_account", "github", "model", "replies_in_threads"]),
        (
            "installer",
            ["link_account", "ai_consent", "github", "inbox_channel", "sources", "model", "replies_in_threads"],
        ),
        ("linked_org_admin", ["ai_consent", "model", "replies_in_threads"]),
    ],
)
def test_the_planned_steps_depend_on_the_role(role: str, expected: list[str], org_team_user, link_user) -> None:
    org, team, user = org_team_user
    Organization.objects.filter(id=org.id).update(is_ai_data_processing_approved=False)
    if role == "linked_org_admin":
        OrganizationMembership.objects.filter(user=user, organization=org).update(
            level=OrganizationMembership.Level.ADMIN
        )
        link_user(user)
    integration = _install(team, installer=SLACK_USER_ID if role == "installer" else None)

    with patch(f"{GITHUB_STEP}.has_team_github", return_value=role == "member_with_team_github"):
        plan = plan_onboarding(integration, SLACK_USER_ID)

    assert plan.post is not None and plan.post.planned == expected
