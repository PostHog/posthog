import pytest
from unittest.mock import patch

from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.slack_app.backend.slack_workflow_events import emit_slack_message_event, emit_slack_reaction_event

# Matches the workspace_integration fixture in conftest.
SLACK_TEAM_ID = "T12345"

MESSAGE_EVENT = {
    "type": "message",
    "channel": "C0ALERTS",
    "channel_type": "channel",
    "user": "U123",
    "text": "database is on fire",
    "ts": "1700000000.000100",
}

REACTION_EVENT = {
    "type": "reaction_added",
    "user": "U123",
    "reaction": "mag",
    "item_user": "U-BOT-AUTHOR",
    "item": {"type": "message", "channel": "C0ALERTS", "ts": "1700000000.000100"},
    "event_ts": "1700000001.000200",
}


@pytest.fixture
def produce():
    with patch("products.slack_app.backend.slack_workflow_events.produce_internal_event") as mock:
        yield mock


@pytest.mark.parametrize("enabled", [True, False])
def test_setting_gates_the_emit(produce, workspace_integration, enabled) -> None:
    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", enabled):
        emit_slack_message_event(MESSAGE_EVENT, SLACK_TEAM_ID, event_id="Ev1", is_ext_shared_channel=False)

    assert produce.call_count == (1 if enabled else 0)


def test_emits_once_per_connected_project(produce, org_team_user, workspace_integration) -> None:
    org, first_team, _ = org_team_user
    second_team = Team.objects.create(organization=org, name="Second")
    second_integration = Integration.objects.create(
        team=second_team,
        kind="slack",
        integration_id=SLACK_TEAM_ID,
        sensitive_config={"access_token": "xoxb-test"},
    )

    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_slack_message_event(MESSAGE_EVENT, SLACK_TEAM_ID, event_id="Ev1", is_ext_shared_channel=False)

    assert {call.args[0] for call in produce.call_args_list} == {first_team.pk, second_team.pk}
    # Same Slack event, different projects: the uuids have to differ or the second project's run
    # would be discarded as a duplicate of the first.
    assert len({call.args[1].uuid for call in produce.call_args_list}) == 2
    # The consumer resolves this back to a stored app id to recognize a message PostHog posted, and
    # each project has its own connection.
    assert {call.args[1].properties["integration_id"] for call in produce.call_args_list} == {
        workspace_integration.pk,
        second_integration.pk,
    }


@pytest.mark.parametrize(
    "subtype,emitted",
    [
        (None, True),
        ("bot_message", True),
        ("file_share", True),
        ("message_changed", False),
        ("message_deleted", False),
        ("channel_join", False),
    ],
)
def test_only_a_new_post_is_emitted(produce, workspace_integration, subtype, emitted) -> None:
    event = MESSAGE_EVENT if subtype is None else {**MESSAGE_EVENT, "subtype": subtype}

    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_slack_message_event(event, SLACK_TEAM_ID, event_id="Ev1", is_ext_shared_channel=False)

    assert produce.call_count == (1 if emitted else 0)


def test_emits_nothing_for_an_unconnected_workspace(produce, workspace_integration) -> None:
    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_slack_message_event(MESSAGE_EVENT, "T-OTHER-REGION", event_id="Ev1", is_ext_shared_channel=False)

    produce.assert_not_called()


def test_properties_carry_what_a_filter_needs(produce, workspace_integration) -> None:
    event = {**MESSAGE_EVENT, "thread_ts": "1699999999.000000", "bot_id": "B42"}

    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_slack_message_event(event, SLACK_TEAM_ID, event_id="Ev1", is_ext_shared_channel=True)

    properties = produce.call_args.args[1].properties
    assert properties["channel"] == "C0ALERTS"
    assert properties["bot_id"] == "B42"
    assert properties["is_ext_shared_channel"] is True
    assert properties["is_thread_reply"] is True
    assert properties["slack_event"] == event


def test_a_top_level_post_is_not_a_thread_reply(produce, workspace_integration) -> None:
    event = {**MESSAGE_EVENT, "thread_ts": MESSAGE_EVENT["ts"]}

    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_slack_message_event(event, SLACK_TEAM_ID, event_id="Ev1", is_ext_shared_channel=False)

    assert produce.call_args.args[1].properties["is_thread_reply"] is False


def test_a_kafka_failure_does_not_reach_the_webhook(produce, workspace_integration) -> None:
    produce.side_effect = RuntimeError("kafka is down")

    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_slack_message_event(MESSAGE_EVENT, SLACK_TEAM_ID, event_id="Ev1", is_ext_shared_channel=False)


@pytest.mark.parametrize("enabled", [True, False])
def test_setting_gates_the_reaction_emit(produce, workspace_integration, enabled) -> None:
    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", enabled):
        emit_slack_reaction_event(REACTION_EVENT, SLACK_TEAM_ID, event_id="Ev2", is_ext_shared_channel=False)

    assert produce.call_count == (1 if enabled else 0)


def test_a_reaction_reads_its_channel_and_message_from_the_item(produce, workspace_integration) -> None:
    # Slack files both under `item`, unlike a message, which carries them beside `user`. Reading
    # them from the top level yields a null channel that matches no trigger.
    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_slack_reaction_event(REACTION_EVENT, SLACK_TEAM_ID, event_id="Ev2", is_ext_shared_channel=True)

    properties = produce.call_args.args[1].properties
    assert properties["channel"] == "C0ALERTS"
    assert properties["item_ts"] == "1700000000.000100"
    # Who reacted, versus who wrote the message they reacted to.
    assert properties["user"] == "U123"
    assert properties["item_user"] == "U-BOT-AUTHOR"
    assert properties["is_ext_shared_channel"] is True
    assert properties["slack_event"] == REACTION_EVENT


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("mag", "mag"),
        # A default skin tone rides along on the event. Storing it whole would make the filter
        # someone typed miss every teammate whose tone differs.
        ("+1::skin-tone-3", "+1"),
    ],
)
def test_the_emoji_is_stored_without_its_skin_tone(produce, workspace_integration, raw, expected) -> None:
    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_slack_reaction_event(
            {**REACTION_EVENT, "reaction": raw}, SLACK_TEAM_ID, event_id="Ev2", is_ext_shared_channel=False
        )

    assert produce.call_args.args[1].properties["reaction"] == expected


@pytest.mark.parametrize(
    "item,emitted",
    [
        ({"type": "message", "channel": "C0ALERTS", "ts": "1700000000.000100"}, True),
        # A file reaction names no message, so there is no thread for a run to answer in.
        ({"type": "file", "file": "F123"}, False),
        ({"type": "message", "channel": "C0ALERTS"}, False),
    ],
)
def test_only_a_reaction_on_a_message_is_emitted(produce, workspace_integration, item, emitted) -> None:
    with patch("django.conf.settings.SLACK_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_slack_reaction_event(
            {**REACTION_EVENT, "item": item}, SLACK_TEAM_ID, event_id="Ev2", is_ext_shared_channel=False
        )

    assert produce.call_count == (1 if emitted else 0)
