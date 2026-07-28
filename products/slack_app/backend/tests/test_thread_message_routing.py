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
    """Untagged ``message`` events in already-tagged threads start the mention
    workflow immediately. Classifier + user resolution have moved inside the
    workflow so the webhook handler stays fast."""

    def setUp(self):
        from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES

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
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
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
        # Bob participates in the thread (default ``_make_event`` user). Seed
        # him as a real PostHog user with team access so the user-resolution
        # gate passes for happy-path tests; the silent-drop test deliberately
        # uses a different unknown user id.
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

        # All routing tests assume the per-org feature flag is on. The
        # dedicated ``test_feature_flag_off_dropped`` test stops the patcher
        # to exercise the off path.
        self._ff_patcher = patch(
            "products.slack_app.backend.api.is_slack_app_untagged_thread_followups_enabled", return_value=True
        )
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
        top-level post in the channel, not a thread reply. Drop before
        touching the DB — channel chatter dominates wire volume."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(thread_ts="1001.0000")  # same as ts
        with (
            patch("products.slack_app.backend.api.SlackThreadTaskMapping.objects.filter") as mock_filter,
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_filter.assert_not_called()
        mock_start.assert_not_called()

    def test_no_user_dropped(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(user=None)
        with patch("products.slack_app.backend.api._start_mention_workflow") as mock_start:
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_not_called()

    def test_bot_author_dropped(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(bot_id="B_OTHER")
        with patch("products.slack_app.backend.api._start_mention_workflow") as mock_start:
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_not_called()

    def test_edited_message_dropped(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(subtype="message_changed")
        with patch("products.slack_app.backend.api._start_mention_workflow") as mock_start:
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_not_called()

    # --- Mapping + FF gate -------------------------------------------------

    def test_thread_without_mapping_dropped(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        self.mapping.delete()
        with (
            patch("products.slack_app.backend.api.resolve_user_for_workspace") as mock_resolve,
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            result = self._route(self._make_event())
        assert result == ROUTE_HANDLED_LOCALLY
        mock_resolve.assert_not_called()
        mock_start.assert_not_called()

    def test_feature_flag_off_dropped(self):
        """Off-by-default workspaces pay one DB query and nothing else."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        self._ff_patcher.stop()
        with (
            patch("products.slack_app.backend.api.is_slack_app_untagged_thread_followups_enabled", return_value=False),
            patch("products.slack_app.backend.api.resolve_user_for_workspace") as mock_resolve,
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            result = self._route(self._make_event())
        self._ff_patcher.start()
        assert result == ROUTE_HANDLED_LOCALLY
        mock_resolve.assert_not_called()
        mock_start.assert_not_called()

    # --- Cross-org access gate -------------------------------------------

    def test_user_without_access_to_mapping_team_dropped_silently(self):
        """A workspace can be connected to multiple orgs; the message author
        may belong to a different org than the one that owns the thread's
        mapping. The handler must drop silently rather than dispatch a
        workflow against an integration the user has no access to."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        carol = User.objects.create(email="carol@example.com", distinct_id="user-3")
        OrganizationMembership.objects.create(organization=other_org, user=carol)
        # Carol's only org is "Other Org" — she has no access to ``self.team``,
        # which owns the mapping. The same Slack workspace is wired to both.
        Integration.objects.create(
            team=other_team,
            kind="slack",
            integration_id="T_SLACK",
            config={"scope": self.integration.config["scope"]},
            sensitive_config={"access_token": "xoxb-other"},
        )
        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id="U_CAROL",
            email="carol@example.com",
            display_name="Carol",
            real_name="Carol Example",
            refreshed_at=timezone.now(),
        )

        with patch("products.slack_app.backend.api._start_mention_workflow") as mock_start:
            result = self._route(self._make_event(user="U_CAROL"))
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_not_called()

    # --- User-resolution gate ---------------------------------------------

    def test_unknown_user_dropped_silently(self):
        """An untagged thread message from a Slack user we can't resolve drops
        silently — unlike the mention path, no failure reply is posted, because
        per-observer notices would spam the thread on every message."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(user="U_UNKNOWN")
        with (
            patch("products.slack_app.backend.api._post_user_resolution_failure_reply") as mock_failure,
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_failure.assert_not_called()
        mock_start.assert_not_called()

    # --- Scope + approval gates ------------------------------------------

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_missing_scopes_dropped_silently(self):
        """Scopes can only be missing if they were revoked after the mapping
        was created. Drop silently rather than reposting the notice on every
        message."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        with (
            patch(
                "products.slack_app.backend.api.SlackIntegration.missing_scopes", return_value=frozenset({"chat:write"})
            ),
            patch("products.slack_app.backend.api._notify_missing_slack_scopes") as mock_notify,
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            result = self._route(self._make_event())
        assert result == ROUTE_HANDLED_LOCALLY
        mock_notify.assert_not_called()
        mock_start.assert_not_called()

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_unapproved_ext_shared_channel_dropped_silently(self):
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region

        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        with (
            patch("products.slack_app.backend.api._channel_is_approved", return_value=False),
            patch("products.slack_app.backend.api._post_channel_approval_prompt") as mock_prompt,
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            result = route_posthog_code_event_to_relevant_region(
                request, self._make_event(), "T_SLACK", is_ext_shared_channel=True
            )
        assert result == ROUTE_HANDLED_LOCALLY
        mock_prompt.assert_not_called()
        mock_start.assert_not_called()

    # --- Rules command not invoked for untagged --------------------------

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_rules_command_text_does_not_trigger_command_workflow(self):
        """A rules-shaped message in an untagged thread (no @mention) must not
        kick off the command workflow — the user never tagged us. It should
        flow through to the regular mention workflow with
        ``untagged_followup=True`` so the classifier in the workflow can drop
        it as off-topic."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        rules_text = '@PostHog rules add "use the helper" org/repo'
        with (
            patch("products.slack_app.backend.api._start_command_workflow") as mock_command,
            patch(
                "products.slack_app.backend.api._start_mention_workflow", return_value=ROUTE_HANDLED_LOCALLY
            ) as mock_start,
        ):
            result = self._route(self._make_event(text=rules_text))
        assert result == ROUTE_HANDLED_LOCALLY
        mock_command.assert_not_called()
        mock_start.assert_called_once()
        assert mock_start.call_args.kwargs["untagged_followup"] is True

    # --- Workflow handoff (happy path) -----------------------------------

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_tagged_message_starts_workflow_with_resolved_user_and_untagged_flag(self):
        """Happy path: the handler runs the same gates as a mention but on
        success starts the workflow with ``untagged_followup=True`` and the
        resolved PostHog user. The classifier and thread-history fetch happen
        inside the workflow."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        with patch(
            "products.slack_app.backend.api._start_mention_workflow", return_value=ROUTE_HANDLED_LOCALLY
        ) as mock_start:
            result = self._route(self._make_event(user="U_ALICE"))
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_called_once()
        kwargs = mock_start.call_args.kwargs
        assert kwargs["posthog_user"].id == self.user.id
        assert kwargs["untagged_followup"] is True

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_file_only_reply_reaches_mention_workflow(self):
        """A file-only thread reply has empty text and the ``file_share`` subtype —
        both gates must admit it or attachments silently never reach the agent."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        event = self._make_event(
            user="U_ALICE",
            text="",
            subtype="file_share",
            files=[{"id": "F123", "name": "debug.log"}],
        )
        with patch(
            "products.slack_app.backend.api._start_mention_workflow", return_value=ROUTE_HANDLED_LOCALLY
        ) as mock_start:
            result = self._route(event)
        assert result == ROUTE_HANDLED_LOCALLY
        mock_start.assert_called_once()
        assert mock_start.call_args.kwargs["untagged_followup"] is True

    # --- Symmetry with the app_mention path -------------------------------

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_app_mention_and_tagged_message_both_reach_mention_workflow(self):
        """Both event types end at ``_start_mention_workflow`` with the user
        resolved; only the ``untagged_followup`` kwarg differs."""
        from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY

        mention_event = {
            "type": "app_mention",
            "channel": "C001",
            "user": "U_ALICE",
            "ts": "1000.0000",
            "thread_ts": "1000.0000",
            "text": "<@BOT> please fix the export",
        }
        followup_event = self._make_event(user="U_ALICE")
        with patch(
            "products.slack_app.backend.api._start_mention_workflow", return_value=ROUTE_HANDLED_LOCALLY
        ) as mock_start:
            self._route(mention_event)
            self._route(followup_event)
        assert mock_start.call_count == 2
        first, second = mock_start.call_args_list
        assert first.kwargs.get("untagged_followup", False) is False
        assert first.kwargs["posthog_user"].id == self.user.id
        assert second.kwargs["untagged_followup"] is True
        assert second.kwargs["posthog_user"].id == self.user.id
