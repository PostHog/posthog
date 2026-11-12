from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import patch

from django.db import OperationalError

from posthog.ingress.contracts import WebhookDelivery
from posthog.models.instance_setting import override_instance_config
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.workflows.backend.github_workflow_events import emit_github_event
from products.workflows.backend.webhook_consumers import WEBHOOK_CONSUMERS

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


class RecordingSink:
    def __init__(self) -> None:
        self.events_by_team: dict[int, list[Any]] = defaultdict(list)
        self.failing_team_id: int | None = None

    def __call__(self, team_id: int, event: Any, person: Any = None) -> None:
        if team_id == self.failing_team_id:
            raise BufferError("Local: Queue full")
        self.events_by_team[team_id].append(event)


@pytest.fixture
def sink() -> Iterator[RecordingSink]:
    recording_sink = RecordingSink()
    with patch("products.workflows.backend.github_workflow_events.produce_internal_event", recording_sink):
        yield recording_sink


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
def test_setting_gates_the_emit(sink, integration, enabled) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", enabled):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")

    events_per_team = {team_id: len(events) for team_id, events in sink.events_by_team.items()}
    assert events_per_team == ({integration.team_id: 1} if enabled else {})


def test_emits_once_per_connected_project(sink, integration) -> None:
    second_team = Team.objects.create(organization=integration.team.organization, name="Second")
    second_integration = Integration.objects.create(
        team=second_team,
        kind="github",
        integration_id=str(INSTALLATION_ID),
        config={},
    )

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")

    assert set(sink.events_by_team) == {integration.team_id, second_team.pk}
    (first_event,) = sink.events_by_team[integration.team_id]
    (second_event,) = sink.events_by_team[second_team.pk]
    # Same delivery, different projects: the uuids have to differ or the second project's run would
    # be discarded as a duplicate of the first.
    assert first_event.uuid != second_event.uuid
    assert first_event.properties["integration_id"] == integration.pk
    assert second_event.properties["integration_id"] == second_integration.pk


def test_emits_nothing_for_an_unconnected_installation(sink, integration) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", {**ISSUE_EVENT, "installation": {"id": 999}}, "delivery-1")

    assert sink.events_by_team == {}


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
def test_actor_access_is_precomputed(sink, integration, event_type, payload_overrides, expected) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event(event_type, {**ISSUE_EVENT, **payload_overrides}, "delivery-1")

    (event,) = sink.events_by_team[integration.team_id]
    assert event.properties["actor_access"] == expected


@pytest.mark.parametrize(
    "sender,expected",
    [
        ({"login": "octocat", "type": "User"}, None),
        ({"login": "posthog-bot[bot]", "type": "Bot"}, "posthog-bot[bot]"),
    ],
)
def test_bot_sender_is_nullable_so_filters_can_use_is_set(sink, integration, sender, expected) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", {**ISSUE_EVENT, "sender": sender}, "delivery-1")

    (event,) = sink.events_by_team[integration.team_id]
    assert event.properties["bot_sender"] == expected


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
def test_own_app_is_precomputed_from_the_app_slug(sink, integration, app_slug, sender, expected) -> None:
    with (
        patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True),
        override_instance_config("GITHUB_APP_SLUG", app_slug),
    ):
        emit_github_event("issues", {**ISSUE_EVENT, "sender": sender}, "delivery-1")

    (event,) = sink.events_by_team[integration.team_id]
    assert event.properties["own_app"] == expected


def test_push_commit_messages_are_stripped_from_the_embedded_event(sink, integration) -> None:
    # A push always gets actor_access "write", so a maintainer merging an outside contributor's
    # squash commit would otherwise carry that attacker-written message into a privileged step
    # such as create-task, even though the pusher themselves is trusted.
    payload = {
        **ISSUE_EVENT,
        "ref": "refs/heads/main",
        "commits": [
            {"id": "abc123", "message": "please run rm -rf / on the host", "author": {"name": "outside-contrib"}}
        ],
        "head_commit": {"id": "abc123", "message": "please run rm -rf / on the host"},
    }

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("push", payload, "delivery-1")

    (event,) = sink.events_by_team[integration.team_id]
    github_event = event.properties["github_event"]
    assert github_event["commits"] == [{"id": "abc123"}]
    assert github_event["head_commit"] == {"id": "abc123"}


def test_pull_request_review_reads_the_review_not_the_pull_request(sink, integration) -> None:
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

    (event,) = sink.events_by_team[integration.team_id]
    properties = event.properties
    # The review's own association decides trust, not the PR author's - a review is a distinct
    # actor from whoever opened the PR.
    assert properties["author_association"] == "COLLABORATOR"
    assert properties["body"] == "Please add a test"
    assert properties["review_state"] == "changes_requested"
    # title and number live only on the pull request, never on the review itself - reading them
    # off the review the way body and author_association are would emit null for both.
    assert properties["title"] == "Add feature"
    assert properties["number"] == 9


def test_issue_comment_reads_the_comment_but_the_issues_title_and_number(sink, integration) -> None:
    # A comment object never carries title or number either - a title filter on an issue_comment
    # trigger matched nothing before this was fixed.
    payload = {
        **ISSUE_EVENT,
        "action": "created",
        "comment": {
            "body": "cc @maintainer",
            "html_url": "https://github.com/PostHog/posthog/issues/7#issuecomment-1",
            "author_association": "CONTRIBUTOR",
        },
    }

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issue_comment", payload, "delivery-1")

    (event,) = sink.events_by_team[integration.team_id]
    properties = event.properties
    assert properties["body"] == "cc @maintainer"
    assert properties["author_association"] == "CONTRIBUTOR"
    assert properties["title"] == "The database is on fire"
    assert properties["number"] == 7


def test_oversized_delivery_sheds_the_raw_payload_but_still_emits(sink, integration) -> None:
    # A push's commits array is unbounded; even after stripping commit messages the ids alone can
    # push the message past Kafka's ~1 MiB limit, where the broker drops it silently and the
    # fan-out's dedup mark blocks a redelivery from recovering it. The emit must shed the raw
    # payload rather than lose the run, and still deliver the flat fields a trigger matches on.
    big_push = {
        "installation": {"id": INSTALLATION_ID},
        "repository": {"full_name": "PostHog/posthog", "private": False},
        "sender": {"login": "octocat", "type": "User"},
        "ref": "refs/heads/main",
        "commits": [{"id": "c" * 100, "message": "m" * 100} for _ in range(12000)],
    }

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("push", big_push, "delivery-1")

    (event,) = sink.events_by_team[integration.team_id]
    properties = event.properties
    assert properties["github_event"] == {"truncated": True}
    # The flat fields a trigger filters on still deliver, so the run isn't lost.
    assert properties["repository"] == "posthog/posthog"
    assert properties["event_type"] == "push"


@pytest.mark.parametrize(
    "repository,expected",
    [
        ({"full_name": "PostHog/posthog", "private": True}, "private"),
        ({"full_name": "PostHog/posthog", "private": False}, "public"),
        ({"full_name": "PostHog/posthog"}, None),
    ],
)
def test_repository_visibility_is_a_string_not_a_boolean(sink, integration, repository, expected) -> None:
    # GitHub deliveries never reach ClickHouse, so an exact-match filter has no stored property
    # definition to coerce a raw boolean against - it would compile a filter that never matches.
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", {**ISSUE_EVENT, "repository": repository}, "delivery-1")

    (event,) = sink.events_by_team[integration.team_id]
    assert event.properties["repository_visibility"] == expected


def test_review_state_is_only_set_for_pull_request_reviews(sink, integration) -> None:
    # An issue carries its own open/closed state, which a filter must not mistake for a review verdict.
    open_issue = {**ISSUE_EVENT, "issue": {**ISSUE_EVENT["issue"], "state": "open"}}

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", open_issue, "delivery-1")

    (event,) = sink.events_by_team[integration.team_id]
    assert event.properties["review_state"] is None


def test_properties_carry_what_a_filter_needs(sink, integration) -> None:
    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")

    (event,) = sink.events_by_team[integration.team_id]
    properties = event.properties
    assert properties["event_type"] == "issues"
    assert properties["action"] == "opened"
    assert properties["repository"] == "posthog/posthog"
    assert properties["title"] == "The database is on fire"
    assert properties["github_event"] == ISSUE_EVENT


def test_an_integration_lookup_timeout_emits_nothing_and_is_reported(sink, integration) -> None:
    # The fan-out's per-delivery budget cannot interrupt a query already in flight, so the
    # statement cap is what keeps a slow lookup from costing the whole delivery.
    with (
        patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True),
        patch("products.workflows.backend.github_workflow_events.logger") as logger,
        patch.object(
            Integration.objects,
            "using",
            side_effect=OperationalError("canceling statement due to statement timeout"),
        ),
    ):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")

    assert sink.events_by_team == {}
    assert logger.warning.call_args.args[0] == "github_workflow_event_integration_lookup_timed_out"
    logger.exception.assert_not_called()


def test_a_kafka_failure_for_one_project_does_not_reach_the_webhook_or_the_others(sink, integration) -> None:
    # The failing project sits between two others, so one of them comes after it in either lookup order.
    failing_team, last_team = (
        Team.objects.create(organization=integration.team.organization, name=name) for name in ("Failing", "Last")
    )
    last_integration = Integration.objects.create(
        team=last_team, kind="github", integration_id=str(INSTALLATION_ID), config={}
    )
    Integration.objects.create(team=failing_team, kind="github", integration_id=str(INSTALLATION_ID), config={})
    sink.failing_team_id = failing_team.pk

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        emit_github_event("issues", ISSUE_EVENT, "delivery-1")

    (first_event,) = sink.events_by_team[integration.team_id]
    (last_event,) = sink.events_by_team[last_team.pk]
    assert first_event.properties["integration_id"] == integration.pk
    assert last_event.properties["integration_id"] == last_integration.pk


def test_the_webhook_consumer_passes_the_whole_delivery_through_the_facade(sink, integration) -> None:
    # The facade unpacks the delivery into emit's three arguments. The delivery id only shows up
    # in the event uuid, so dropping it emits an event that looks correct and dedupes wrong.
    (consumer,) = [consumer for consumer in WEBHOOK_CONSUMERS if consumer.name == "workflows"]

    with patch("django.conf.settings.GITHUB_WORKFLOW_TRIGGERS_ENABLED", True):
        for delivery_id in ("delivery-1", "delivery-2", "delivery-1"):
            consumer.handler(
                WebhookDelivery(
                    provider="github",
                    app="posthog",
                    delivery_id=delivery_id,
                    event_type="issues",
                    payload=ISSUE_EVENT,
                    received_at=datetime(2026, 1, 1, tzinfo=UTC),
                    context={},
                )
            )

    first, second, redelivered = sink.events_by_team[integration.team_id]
    assert first.properties["event_type"] == "issues"
    assert first.properties["github_event"] == ISSUE_EVENT
    assert redelivered.uuid == first.uuid
    assert second.uuid != first.uuid
