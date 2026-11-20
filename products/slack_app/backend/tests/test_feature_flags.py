import pytest
from unittest.mock import patch

from posthog.models.integration import Integration

from products.slack_app.backend import feature_flags
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID

# (gate, scopes the feature calls)
SCOPED_GATES = [
    (feature_flags.is_slack_app_oauth_enabled, feature_flags.OAUTH_REQUIRED_SCOPES),
    (feature_flags.is_slack_app_assistant_enabled, feature_flags.ASSISTANT_REQUIRED_SCOPES),
]

IDS = [gate.__name__ for gate, *_ in SCOPED_GATES]


def _grant(integration, scopes):
    integration.config = {"scope": ",".join(sorted(scopes))}
    integration.save()


@pytest.mark.parametrize(("gate", "required"), SCOPED_GATES, ids=IDS)
def test_gate_opens_when_the_scopes_are_granted(workspace_integration, gate, required):
    _grant(workspace_integration, required)

    assert gate(workspace_integration) is True


@pytest.mark.parametrize(("gate", "required"), SCOPED_GATES, ids=IDS)
def test_gate_stays_closed_when_a_required_scope_is_missing(workspace_integration, gate, required):
    _grant(workspace_integration, required - {min(required)})

    assert gate(workspace_integration) is False


USER_KEYED_GATES = [
    feature_flags.is_slack_app_agent_design_enabled,
    feature_flags.is_slack_app_onboarding_enabled,
    feature_flags.is_slack_app_link_search_scopes_enabled,
    feature_flags.is_slack_app_connect_tool_from_chat_enabled,
    feature_flags.is_slack_app_daily_work_focus_enabled,
    feature_flags.is_slack_app_slack_mcp_enabled,
]


@pytest.mark.parametrize("gate", USER_KEYED_GATES, ids=[gate.__name__ for gate in USER_KEYED_GATES])
@pytest.mark.parametrize(
    ("distinct_id", "expected_identity"),
    [
        ("user-1", "user-1"),
        (None, f"slack_workspace:{SLACK_TEAM_ID}"),
    ],
    ids=["known user", "no user"],
)
def test_user_keyed_gate_resolves_against_the_acting_user(
    settings, workspace_integration, org_team_user, gate, distinct_id, expected_identity
):
    # The identity decides which rules can match at all. Resolving a known user against the
    # workspace instead would silently stop every person rule, `email ends_with
    # @posthog.com` included, from matching anyone.
    settings.CLOUD_DEPLOYMENT = "DEV"
    org, _, _ = org_team_user

    with patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled:
        assert gate(workspace_integration, distinct_id) is True

    assert feature_enabled.call_args.args[1] == expected_identity
    assert feature_enabled.call_args.kwargs["person_properties"] == {"region": "DEV"}
    assert feature_enabled.call_args.kwargs["groups"] == {"organization": str(org.id)}


@pytest.mark.parametrize(
    ("adapter", "distinct_id", "plan_rollout_on", "expected"),
    [
        ("codex", "user-1", False, True),
        ("codex", None, True, False),
        ("claude", "user-1", True, True),
        ("claude", "user-1", False, False),
    ],
    ids=["codex is open", "codex needs a user", "claude rollout on", "claude rollout off"],
)
def test_byos_gate_follows_the_plan_rollout(
    workspace_integration: Integration, adapter: str, distinct_id: str | None, plan_rollout_on: bool, expected: bool
) -> None:
    # A Slack run marked for a plan whose rollout is off fails when it starts, so the gate
    # must match the tasks rollout for that plan exactly.
    with patch("posthoganalytics.feature_enabled", return_value=plan_rollout_on):
        assert feature_flags.is_slack_app_byos_enabled(workspace_integration, distinct_id, adapter=adapter) is expected
