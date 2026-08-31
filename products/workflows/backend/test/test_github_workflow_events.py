from typing import Any

import pytest
from unittest.mock import patch

from posthog.models.instance_setting import override_instance_config
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.workflows.backend.github_workflow_events import emit_github_event

INSTALLATION_ID = 4242

ISSUE_EVENT: dict[str, Any] = {
    "action": "opened",
    "installation": {"id": INSTALLATION_ID},
    "repository": {"full_name": "PostHog/posthog", "private": False},
    "sender": {"login": "octocat", "type": "User"},
    "issue": {
        "number": 7,
        "title": "The database is on fire",
        "body": "everything is fine",
        "html_url": "https://github.com/PostHog/posthog/issues/7",
        "author_association": "MEMBER",
    },
}


@pytest.fixture
def produce():
    with patch("products.workflows.backend.github_workflow_events.produce_internal_event") as mock:
        yield mock


@pytest.fixture
def integration(db):
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org, name="Test")
    return Integration.objects.create(
        team=team,
        kind="github",
        integration_id=str(INSTALLATION_ID),
        config={"account": {"name": "PostHog"}},
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_setting_gates_the_emit(produce, integration, enabled) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", enabled):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")

    assert produce.call_count == (1 if enabled else 0)


def test_emits_once_per_connected_project(produce, integration) -> None:
    second_team = Team.objects.create(organization=integration.team.organization, name="Second")
    second_integration = Integration.objects.create(
        team=second_team,
        kind="github",
        integration_id=str(INSTALLATION_ID),
        config={},
    )

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")

    assert {call.args[0] for call in produce.call_args_list} == {integration.team_id, second_team.pk}
    # Same delivery, different projects: the uuids have to differ or the second project's run would
    # be discarded as a duplicate of the first.
    assert len({call.args[1].uuid for call in produce.call_args_list}) == 2
    assert {call.args[1].properties["integration_id"] for call in produce.call_args_list} == {
        integration.pk,
        second_integration.pk,
    }


def test_emits_nothing_for_an_unconnected_installation(produce, integration) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", {**ISSUE_EVENT, "installation": {"id": 999}}, "delivery-1")

    produce.assert_not_called()


@pytest.mark.parametrize(
    "event_type,payload_overrides,expected",
    [
        ("issues", {}, "write"),
        ("issues", {"issue": {**ISSUE_EVENT["issue"], "author_association": "NONE"}}, "read"),
        ("issues", {"issue": {**ISSUE_EVENT["issue"], "author_association": "CONTRIBUTOR"}}, "read"),
        # A push needs write access to happen at all, and carries no association to read.
        ("push", {"ref": "refs/heads/main"}, "write"),
    ],
)
def test_actor_access_is_precomputed(produce, integration, event_type, payload_overrides, expected) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event(event_type, {**ISSUE_EVENT, **payload_overrides}, "delivery-1")

    assert produce.call_args.args[1].properties["actor_access"] == expected


@pytest.mark.parametrize(
    "sender,expected",
    [
        ({"login": "octocat", "type": "User"}, None),
        ({"login": "posthog-bot[bot]", "type": "Bot"}, "posthog-bot[bot]"),
    ],
)
def test_bot_sender_is_nullable_so_filters_can_use_is_set(produce, integration, sender, expected) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", {**ISSUE_EVENT, "sender": sender}, "delivery-1")

    assert produce.call_args.args[1].properties["bot_sender"] == expected


@pytest.mark.parametrize(
    "app_slug,sender,expected",
    [
        # A workflow's own comment must be recognized, or it retriggers itself forever.
        ("posthog-bot", {"login": "posthog-bot[bot]", "type": "Bot"}, True),
        ("posthog-bot", {"login": "dependabot[bot]", "type": "Bot"}, False),
        ("posthog-bot", {"login": "posthog-bot", "type": "User"}, False),
        # No configured app slug must not crash, and must not treat every bot as "us".
        ("", {"login": "posthog-bot[bot]", "type": "Bot"}, False),
    ],
)
def test_own_app_is_precomputed_from_the_app_slug(produce, integration, app_slug, sender, expected) -> None:
    with (
        patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True),
        override_instance_config("GITHUB_APP_SLUG", app_slug),
    ):
        emit_github_event("issues", {**ISSUE_EVENT, "sender": sender}, "delivery-1")

    assert produce.call_args.args[1].properties["own_app"] == expected


def test_pull_request_review_reads_the_review_not_the_pull_request(produce, integration) -> None:
    payload = {
        **ISSUE_EVENT,
        "action": "submitted",
        "review": {
            "body": "Please add a test",
            "state": "changes_requested",
            "html_url": "https://github.com/PostHog/posthog/pull/9#pullrequestreview-1",
            "author_association": "COLLABORATOR",
        },
        "pull_request": {"number": 9, "title": "Add feature", "author_association": "NONE"},
    }

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("pull_request_review", payload, "delivery-1")

    properties = produce.call_args.args[1].properties
    # The review's own association decides trust, not the PR author's - a review is a distinct
    # actor from whoever opened the PR.
    assert properties["author_association"] == "COLLABORATOR"
    assert properties["body"] == "Please add a test"
    assert properties["review_state"] == "changes_requested"


def test_review_state_is_only_set_for_pull_request_reviews(produce, integration) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")

    assert produce.call_args.args[1].properties["review_state"] is None


def test_properties_carry_what_a_filter_needs(produce, integration) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")

    properties = produce.call_args.args[1].properties
    assert properties["event_type"] == "issues"
    assert properties["action"] == "opened"
    assert properties["repository"] == "PostHog/posthog"
    assert properties["title"] == "The database is on fire"
    assert properties["github_event"] == ISSUE_EVENT


def test_a_kafka_failure_does_not_reach_the_webhook(produce, integration) -> None:
    produce.side_effect = RuntimeError("kafka is down")

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")
