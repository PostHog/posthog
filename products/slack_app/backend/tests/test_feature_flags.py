import pytest
from unittest.mock import patch

from products.slack_app.backend import feature_flags
from products.slack_app.backend.models import SlackUserProfileCache
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID

PERSON_GATES = [
    feature_flags.is_slack_app_onboarding_enabled,
    feature_flags.is_slack_app_link_search_scopes_enabled,
    feature_flags.is_slack_app_connect_tool_from_chat_enabled,
    feature_flags.is_slack_app_daily_work_focus_enabled,
    feature_flags.is_slack_app_slack_mcp_enabled,
]

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


@pytest.mark.parametrize(
    "gate",
    [feature_flags.is_slack_app_agent_design_enabled],
    ids=["agent design"],
)
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
        gate(workspace_integration, distinct_id)

    assert feature_enabled.call_args.args[1] == expected_identity
    assert feature_enabled.call_args.kwargs["person_properties"] == {"region": "DEV"}
    assert feature_enabled.call_args.kwargs["groups"] == {"organization": str(org.id)}


@pytest.mark.parametrize("gate", PERSON_GATES, ids=[gate.__name__ for gate in PERSON_GATES])
@pytest.mark.parametrize(
    ("linked", "cached_email", "user_passed"),
    [
        (False, None, False),
        (False, "cached@example.com", False),
        (True, "cached@example.com", False),
        (False, None, True),
    ],
    ids=["unknown person", "cached profile", "linked user", "user from the caller"],
)
def test_person_gate_resolves_against_the_person_not_the_workspace(
    settings, workspace_integration, org_team_user, link_user, gate, linked, cached_email, user_passed
):
    # Keyed on the workspace, a rule on `email` would match nobody, and the only way to turn a feature on for one
    # tester would be to turn it on for everyone in their workspace.
    settings.CLOUD_DEPLOYMENT = "DEV"
    org, _, user = org_team_user
    if linked:
        link_user(user)
    if cached_email:
        SlackUserProfileCache.objects.create(
            integration=workspace_integration, slack_user_id=SLACK_USER_ID, email=cached_email
        )

    with patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled:
        assert gate(workspace_integration, SLACK_USER_ID, user=user if user_passed else None) is True

    if linked or user_passed:
        expected_identity, expected_email = user.distinct_id, user.email
    else:
        expected_identity, expected_email = f"slack:{SLACK_TEAM_ID}:{SLACK_USER_ID}", cached_email
    assert feature_enabled.call_args.args[1] == expected_identity
    assert feature_enabled.call_args.kwargs["person_properties"] == {
        "region": "DEV",
        **({"email": expected_email} if expected_email else {}),
    }
    assert feature_enabled.call_args.kwargs["groups"] == {"organization": str(org.id)}


@pytest.mark.parametrize(
    ("plan_rollout_on", "slack_flag_on", "expected"),
    [(True, True, True), (False, True, False), (True, False, False)],
    ids=["both on", "plan rollout off", "slack flag off"],
)
def test_byos_gate_depends_on_the_plan_rollout_flag(workspace_integration, plan_rollout_on, slack_flag_on, expected):
    # A Slack run marked for a plan whose rollout is off fails when it starts, so the Slack
    # flag alone must never open the gate.
    def feature_enabled(key, *args, **kwargs):
        if key == feature_flags.SLACK_APP_BYOS_FLAG:
            return slack_flag_on
        return plan_rollout_on

    with patch("posthoganalytics.feature_enabled", side_effect=feature_enabled):
        assert feature_flags.is_slack_app_byos_enabled(workspace_integration, "user-1") is expected
