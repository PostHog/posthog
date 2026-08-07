from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.test.client import RequestFactory
from django.utils import timezone

from parameterized import parameterized

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

API_MODULE = "products.slack_app.backend.api"


class TestRouteChannelMessageToLoopTriggers(TestCase):
    """Loop triggers watch a whole channel, so they see messages the thread-follow-up path
    drops: top-level posts, and posts by an app rather than a person. These cover the
    handler opening up for those without changing what the follow-up path does."""

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="alice@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)

        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_SLACK",
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-test"},
        )

        self._has_triggers = patch(f"{API_MODULE}.tasks_webhooks_facade.slack_workspace_has_loop_triggers")
        self.mock_has_triggers = self._has_triggers.start()
        self.mock_has_triggers.return_value = True
        self.addCleanup(self._has_triggers.stop)

        self._flag = patch(f"{API_MODULE}.is_slack_app_loop_triggers_enabled", return_value=True)
        self._flag.start()
        self.addCleanup(self._flag.stop)

    def _make_event(self, **overrides) -> dict:
        event = {
            "type": "message",
            "channel": "C001",
            "user": "U_ALICE",
            "ts": "1001.0000",
            "text": "Incident declared: checkout is down",
        }
        event.update(overrides)
        return event

    def _route(self, event: dict) -> str:
        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        return route_posthog_code_event_to_relevant_region(request, event, "T_SLACK", event_id="Ev001")

    @parameterized.expand(
        [
            # The handler used to drop every top-level post before any DB hit, so this is the
            # gate the whole feature depends on.
            ("a top level post", {}),
            # An alerting app posts under a bot id with no user, which the follow-up path drops
            # outright as bot authorship.
            ("an app-authored post", {"bot_id": "B_INCIDENT", "user": None}),
            ("a post carrying only blocks", {"text": "", "blocks": [{"type": "section"}]}),
        ]
    )
    def test_loop_matching_sees(self, _name, overrides):
        with patch(f"{API_MODULE}.tasks_webhooks_facade.handle_slack_message_for_loops") as mock_handle:
            self._route(self._make_event(**overrides))

        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args.kwargs["event_id"], "Ev001")

    @parameterized.expand(
        [
            ("an edit", {"subtype": "message_changed"}),
            ("a deletion", {"subtype": "message_deleted"}),
            ("a message with nothing to match on", {"text": ""}),
        ]
    )
    def test_loop_matching_does_not_see(self, _name, overrides):
        with patch(f"{API_MODULE}.tasks_webhooks_facade.handle_slack_message_for_loops") as mock_handle:
            self._route(self._make_event(**overrides))

        mock_handle.assert_not_called()

    def test_workspace_without_triggers_never_reaches_loop_matching(self):
        # The cached precheck is what keeps Slack's message firehose off the database now that
        # top-level posts are admitted at all.
        self.mock_has_triggers.return_value = False

        with patch(f"{API_MODULE}.tasks_webhooks_facade.handle_slack_message_for_loops") as mock_handle:
            self._route(self._make_event())

        mock_handle.assert_not_called()

    def test_flag_off_never_reaches_loop_matching(self):
        with (
            patch(f"{API_MODULE}.is_slack_app_loop_triggers_enabled", return_value=False),
            patch(f"{API_MODULE}.tasks_webhooks_facade.handle_slack_message_for_loops") as mock_handle,
        ):
            self._route(self._make_event())

        mock_handle.assert_not_called()

    @parameterized.expand(
        [
            ("a top level post", {}),
            ("an app-authored post", {"bot_id": "B_INCIDENT", "user": None}),
        ]
    )
    def test_follow_up_pipeline_still_drops_what_it_always_dropped(self, _name, overrides):
        # Admitting a message for trigger matching must not leak it into the agent-followup
        # path, which wants a much narrower set: human-authored replies in a tagged thread.
        with (
            patch(f"{API_MODULE}.tasks_webhooks_facade.handle_slack_message_for_loops"),
            patch(f"{API_MODULE}._start_mention_workflow") as mock_start,
            patch(f"{API_MODULE}.try_ingest_discussion_reply") as mock_ingest,
        ):
            self._route(self._make_event(**overrides))

        mock_start.assert_not_called()
        mock_ingest.assert_not_called()

    @parameterized.expand([("unapproved", False, False), ("approved", True, True)])
    def test_externally_shared_channel_waits_for_approval(self, _name, approve, should_dispatch):
        # The run's report lands in a channel another company reads, so it waits on the same
        # approval every other agent surface does. A loop fire returns before the handler's own
        # approval gate, so skipping this would make it the one way around it.
        from products.slack_app.backend.models import SlackChannel

        if approve:
            SlackChannel.objects.create(
                slack_workspace_id="T_SLACK",
                slack_channel_id="C001",
                approved_at=timezone.now(),
                approved_by=self.user,
            )

        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        with patch(f"{API_MODULE}.tasks_webhooks_facade.handle_slack_message_for_loops") as mock_handle:
            route_posthog_code_event_to_relevant_region(
                request, self._make_event(), "T_SLACK", event_id="Ev001", is_ext_shared_channel=True
            )

        self.assertEqual(mock_handle.called, should_dispatch)

    def test_only_flag_enabled_organizations_are_passed_to_matching(self):
        # A workspace can be connected to several organizations, and the rollout flag is per
        # organization. One org's verdict must not decide for the rest.
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_integration = Integration.objects.create(
            team=other_team,
            kind="slack",
            integration_id="T_SLACK",
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-test"},
        )

        with (
            patch(
                f"{API_MODULE}.is_slack_app_loop_triggers_enabled",
                side_effect=lambda integration, _team: integration.id == other_integration.id,
            ),
            patch(f"{API_MODULE}.tasks_webhooks_facade.handle_slack_message_for_loops") as mock_handle,
        ):
            self._route(self._make_event())

        self.assertEqual(
            [i.id for i in mock_handle.call_args.kwargs["integrations"]],
            [other_integration.id],
        )

    def test_a_failure_in_loop_matching_does_not_break_the_shared_handler(self):
        # This handler also carries thread follow-ups, and Slack retries are dropped upstream,
        # so an exception here would silently lose unrelated routing.
        with (
            patch(
                f"{API_MODULE}.tasks_webhooks_facade.handle_slack_message_for_loops",
                side_effect=RuntimeError("boom"),
            ),
            patch(f"{API_MODULE}._start_mention_workflow"),
        ):
            from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

            self.assertEqual(self._route(self._make_event()), ROUTE_HANDLED_LOCALLY)

    @parameterized.expand([("a loop run", "loop", False), ("a mention", "slack", True)])
    def test_a_thread_bound_to_a_loop_run_is_not_an_untagged_followup_target(
        self, _name, origin_product, should_resolve
    ):
        # A loop's trigger decides who may drive it (`allowed_posters`), and the follow-up path
        # doesn't know that rule — it only checks project access. Forwarding here would let a
        # teammate steer a run whose trigger says "only the owner" or "only this alerting app".
        from django.apps import apps

        from products.slack_app.backend.api import _resolve_untagged_followup_mapping
        from products.slack_app.backend.models import SlackThreadTaskMapping

        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team,
            title="Run",
            description="d",
            origin_product=origin_product,
            created_by=self.user,
        )
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C001",
            thread_ts="1000.0000",
            task=task,
            task_run=TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS),
            mentioning_slack_user_id="U_ALICE",
        )

        with patch(f"{API_MODULE}.is_slack_app_untagged_thread_followups_enabled", return_value=True):
            mapping = _resolve_untagged_followup_mapping(
                candidates=[self.integration],
                channel="C001",
                thread_ts="1000.0000",
                slack_team_id="T_SLACK",
            )

        self.assertEqual(mapping is not None, should_resolve)
