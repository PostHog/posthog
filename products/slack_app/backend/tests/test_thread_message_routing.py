from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.utils import timezone

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackThreadTaskMapping, SlackUserProfileCache


class TestRouteThreadMessage(TestCase):
    """Untagged ``message`` events in already-tagged threads should be classified
    and forwarded to the running agent. Every gate that fails must fall through
    silently (no Slack reply) — these events fire on every thread message, so a
    spammy failure path is worse than missing the occasional follow-up."""

    def setUp(self):
        from products.slack_app.backend.api import POSTHOG_CODE_REQUIRED_SLACK_SCOPES

        cache.clear()
        self.factory = RequestFactory()
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")

        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="alice@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)
        self.user.current_organization = self.organization
        self.user.current_team = self.team
        self.user.save()

        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_SLACK",
            config={"scope": ",".join(sorted(POSTHOG_CODE_REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-test"},
        )
        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id="U_ALICE",
            email="alice@example.com",
            display_name="Alice",
            real_name="Alice Example",
            refreshed_at=timezone.now(),
        )
        # Bob is the "other thread participant" — a valid PostHog user with team
        # access so the user-resolution gate passes. The classifier-decision
        # tests use messages from Bob to verify both branches.
        self.bob = User.objects.create(email="bob@example.com", distinct_id="user-2")
        OrganizationMembership.objects.create(organization=self.organization, user=self.bob)
        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id="U_BOB",
            email="bob@example.com",
            display_name="Bob",
            real_name="Bob Example",
            refreshed_at=timezone.now(),
        )

        self.task = self.Task.objects.create(
            team=self.team,
            title="Fix the broken dashboard export",
            description="desc",
            origin_product=self.Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        self.task_run = self.TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=self.TaskRun.Status.IN_PROGRESS,
        )
        self.mapping = SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C001",
            thread_ts="1000.0000",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_ALICE",
        )

        # All the routing tests assume the per-org feature flag is rolled out to
        # this workspace. The dedicated ``test_feature_flag_off_dropped`` test
        # stops this patcher to exercise the off path.
        self._ff_patcher = patch("products.slack_app.backend.api._untagged_thread_followups_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    # --- Helpers -----------------------------------------------------------

    def _make_event(self, **overrides) -> dict:
        defaults = {
            "type": "message",
            "channel": "C001",
            "user": "U_BOB",
            "ts": "1001.0000",
            "thread_ts": "1000.0000",
            "text": "Could you also check the export filter logic, please",
        }
        defaults.update(overrides)
        return defaults

    def _route(self, event: dict) -> str:
        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        return route_posthog_code_event_to_relevant_region(request, event, "T_SLACK")

    # --- Cheap pre-DB gates ------------------------------------------------

    def test_top_level_message_dropped_before_db(self):
        """A message with no ``thread_ts`` (or where ``thread_ts == ts``) is a
        top-level post in the channel, not a thread reply. Drop before touching
        the DB — channel chatter dominates wire volume."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(thread_ts="1001.0000")  # same as ts
        with patch("products.slack_app.backend.api.SlackThreadTaskMapping.objects.filter") as mock_filter:
            with (
                patch("products.slack_app.backend.api.classify_message_is_agent_directed") as mock_classify,
                patch("products.slack_app.backend.api._start_thread_followup_workflow") as mock_start,
            ):
                result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_filter.assert_not_called()
        mock_classify.assert_not_called()
        mock_start.assert_not_called()

    def test_no_user_dropped(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(user=None)
        with patch("products.slack_app.backend.api._start_thread_followup_workflow") as mock_start:
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_not_called()

    def test_bot_author_dropped(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(bot_id="B_OTHER")
        with patch("products.slack_app.backend.api._start_thread_followup_workflow") as mock_start:
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_not_called()

    def test_edited_message_dropped(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(subtype="message_changed")
        with patch("products.slack_app.backend.api._start_thread_followup_workflow") as mock_start:
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_not_called()

    # --- Mapping gate ------------------------------------------------------

    def test_thread_without_mapping_dropped(self):
        """A threaded reply in a channel where this workspace has integrations
        but no mapping for the thread must drop before user resolution and
        before any LLM call."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        self.mapping.delete()
        with (
            patch("products.slack_app.backend.api.resolve_user_for_workspace") as mock_resolve,
            patch("products.slack_app.backend.api.classify_message_is_agent_directed") as mock_classify,
            patch("products.slack_app.backend.api._start_thread_followup_workflow") as mock_start,
        ):
            result = self._route(self._make_event())
        assert result == ROUTE_HANDLED_LOCALLY
        mock_resolve.assert_not_called()
        mock_classify.assert_not_called()
        mock_start.assert_not_called()

    # --- User resolution gate ---------------------------------------------

    def test_unknown_user_dropped_silently(self):
        """An untagged thread message from a Slack user we can't resolve to a
        PostHog account must drop silently. Unlike the ``app_mention`` path, we
        do NOT post a 'couldn't find you' reply — that path runs on every
        message and would spam the thread for observers."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(user="U_UNKNOWN")
        with (
            patch("products.slack_app.backend.api._post_user_resolution_failure_reply") as mock_post_failure,
            patch("products.slack_app.backend.api._start_thread_followup_workflow") as mock_start,
        ):
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_post_failure.assert_not_called()
        mock_start.assert_not_called()

    # --- Feature flag gate ------------------------------------------------

    def test_feature_flag_off_dropped(self):
        """With the per-org untagged-thread-followups flag off, the routing must
        drop after the mapping query — no user resolution, no classifier call,
        no workflow start. This is the kill-switch the rollout depends on."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        # Override the setUp patcher so this test exercises the off branch.
        self._ff_patcher.stop()
        with (
            patch("products.slack_app.backend.api._untagged_thread_followups_enabled", return_value=False),
            patch("products.slack_app.backend.api.resolve_user_for_workspace") as mock_resolve,
            patch("products.slack_app.backend.api.classify_message_is_agent_directed") as mock_classify,
            patch("products.slack_app.backend.api._start_thread_followup_workflow") as mock_start,
        ):
            result = self._route(self._make_event())
        # Restart so addCleanup doesn't double-stop.
        self._ff_patcher.start()
        assert result == ROUTE_HANDLED_LOCALLY
        mock_resolve.assert_not_called()
        mock_classify.assert_not_called()
        mock_start.assert_not_called()

    # --- Classifier bypass / decisions ------------------------------------

    @override_settings(DEBUG=False)
    def test_mentioning_user_bypasses_classifier_and_forwards(self):
        """Messages from the user who originally tagged the bot are always
        forwarded — they're presumed to be talking to the agent. The classifier
        must not be invoked at all for this path."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(user="U_ALICE")
        with (
            patch("products.slack_app.backend.api.classify_message_is_agent_directed") as mock_classify,
            patch(
                "products.slack_app.backend.api._start_thread_followup_workflow", return_value=ROUTE_HANDLED_LOCALLY
            ) as mock_start,
        ):
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_classify.assert_not_called()
        mock_start.assert_called_once()
        # Verify the resolved user was threaded into the start call.
        kwargs = mock_start.call_args.kwargs
        assert kwargs["posthog_user"].id == self.user.id

    @override_settings(DEBUG=False)
    def test_other_user_agent_directed_forwards(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        with (
            patch(
                "products.slack_app.backend.api._collect_thread_messages",
                return_value=[{"user": "Alice", "text": "@PostHog please fix X", "ts": "1000.0000"}],
            ) as mock_collect,
            patch(
                "products.slack_app.backend.api.classify_message_is_agent_directed", return_value=True
            ) as mock_classify,
            patch(
                "products.slack_app.backend.api._start_thread_followup_workflow", return_value=ROUTE_HANDLED_LOCALLY
            ) as mock_start,
        ):
            result = self._route(self._make_event())
        assert result == ROUTE_HANDLED_LOCALLY
        mock_collect.assert_called_once()
        mock_classify.assert_called_once()
        # The classifier prompt should carry the task title and the thread history.
        call_args = mock_classify.call_args[0]
        assert call_args[1] == "Fix the broken dashboard export"
        assert call_args[2] == [{"user": "Alice", "text": "@PostHog please fix X", "ts": "1000.0000"}]
        mock_start.assert_called_once()

    def test_other_user_chitchat_dropped(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        with (
            patch("products.slack_app.backend.api._collect_thread_messages", return_value=[]),
            patch("products.slack_app.backend.api.classify_message_is_agent_directed", return_value=False),
            patch("products.slack_app.backend.api._start_thread_followup_workflow") as mock_start,
        ):
            result = self._route(self._make_event(text="lol thanks for that"))
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_not_called()

    @override_settings(DEBUG=False)
    def test_thread_history_fetch_failure_does_not_crash(self):
        """If Slack hiccups on ``conversations_replies``, classify with empty
        history rather than dropping the event silently or 5xx-ing the webhook."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        with (
            patch(
                "products.slack_app.backend.api._collect_thread_messages",
                side_effect=RuntimeError("slack hiccup"),
            ),
            patch(
                "products.slack_app.backend.api.classify_message_is_agent_directed", return_value=True
            ) as mock_classify,
            patch(
                "products.slack_app.backend.api._start_thread_followup_workflow", return_value=ROUTE_HANDLED_LOCALLY
            ) as mock_start,
        ):
            result = self._route(self._make_event())
        assert result == ROUTE_HANDLED_LOCALLY
        mock_classify.assert_called_once()
        # Empty history passed through on failure.
        assert mock_classify.call_args[0][2] == []
        mock_start.assert_called_once()


class TestClassifyMessageIsAgentDirected(TestCase):
    """The Haiku-backed classifier with cheap pre-LLM heuristics."""

    def test_too_short_dropped_without_llm(self):
        from products.slack_app.backend.api import classify_message_is_agent_directed

        with patch("products.slack_app.backend.api.get_llm_client") as mock_client:
            assert classify_message_is_agent_directed("ok", "do thing", []) is False
            assert classify_message_is_agent_directed("k", "do thing", []) is False
        mock_client.assert_not_called()

    def test_one_word_dropped_without_llm(self):
        from products.slack_app.backend.api import classify_message_is_agent_directed

        with patch("products.slack_app.backend.api.get_llm_client") as mock_client:
            assert classify_message_is_agent_directed("thanksverymuch", "do thing", []) is False
        mock_client.assert_not_called()

    def test_emoji_only_dropped_without_llm(self):
        from products.slack_app.backend.api import classify_message_is_agent_directed

        with patch("products.slack_app.backend.api.get_llm_client") as mock_client:
            assert classify_message_is_agent_directed(":thumbsup: :tada:", "do thing", []) is False
        mock_client.assert_not_called()

    def test_haiku_directed_true(self):
        from products.slack_app.backend.api import classify_message_is_agent_directed

        fake_response = type(
            "Resp",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Msg", (), {"content": '{"agent_directed": true}'})()},
                    )()
                ]
            },
        )()
        with patch("products.slack_app.backend.api.get_llm_client") as mock_client:
            mock_client.return_value.chat.completions.create.return_value = fake_response
            result = classify_message_is_agent_directed("Please also check the auth flow on safari", "fix the bug", [])
        assert result is True

    def test_haiku_directed_false(self):
        from products.slack_app.backend.api import classify_message_is_agent_directed

        fake_response = type(
            "Resp",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Msg", (), {"content": '{"agent_directed": false}'})()},
                    )()
                ]
            },
        )()
        with patch("products.slack_app.backend.api.get_llm_client") as mock_client:
            mock_client.return_value.chat.completions.create.return_value = fake_response
            result = classify_message_is_agent_directed("nice work team, going to lunch now", "fix the bug", [])
        assert result is False

    def test_haiku_failure_defaults_to_drop(self):
        """The conservative default is drop — a false positive interrupts the
        agent on every chit-chat reply, but a false negative just means the
        user re-tags. Opposite of ``classify_task_needs_repo``."""
        from products.slack_app.backend.api import classify_message_is_agent_directed

        with patch("products.slack_app.backend.api.get_llm_client") as mock_client:
            mock_client.return_value.chat.completions.create.side_effect = RuntimeError("boom")
            result = classify_message_is_agent_directed("Please also check the auth flow on safari", "fix the bug", [])
        assert result is False
