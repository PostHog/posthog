import pytest

from products.slack_app.backend import feature_flags

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
