import json

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app.slack_app_fork import (
    FORK_DEFAULT_PROMPT,
    FORK_THREAD_CALLBACK_ID,
    process_slack_app_fork_thread_payload,
)

from products.slack_app.backend.feature_flags import ASSISTANT_REQUIRED_SCOPES
from products.slack_app.backend.tests.helpers import sign_slack_request

_FORK_MODULE = "posthog.temporal.ai.slack_app.slack_app_fork"


class TestForkThreadPayload(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        OrganizationMembership.objects.create(organization=self.org, user=self.user)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_SLACK",
            config={"scope": ",".join(sorted(ASSISTANT_REQUIRED_SCOPES))},
        )

    def _payload(self, **overrides) -> dict:
        payload = {
            "type": "message_action",
            "callback_id": FORK_THREAD_CALLBACK_ID,
            "user": {"id": "U_ALICE"},
            "team": {"id": "T_SLACK"},
            "channel": {"id": "C_SOURCE"},
            "message": {"ts": "111.2", "thread_ts": "111.1", "text": "the discussion"},
            "response_url": "https://hooks.slack.test/resp",
        }
        payload.update(overrides)
        return payload

    def _slack_mock(self, *, ext_shared: bool = False, readable: bool = True) -> MagicMock:
        slack = MagicMock()
        slack.client.conversations_info.return_value = {"channel": {"is_ext_shared": ext_shared}}
        if readable:
            slack.client.conversations_replies.return_value = {"messages": [{"ts": "111.1"}]}
        else:
            slack.client.conversations_replies.side_effect = Exception("not_in_channel")
        slack.client.chat_postMessage.return_value = {"channel": "D_ALICE", "ts": "999.1"}
        return slack

    def _run(self, payload: dict, slack: MagicMock, *, flag: bool = True):
        """Drive the payload with the Slack client and flag stubbed, returning the
        patched ``_start_mention_workflow`` and ephemeral poster for assertions."""
        with (
            patch("posthog.models.integration.SlackIntegration", return_value=slack),
            patch("products.slack_app.backend.feature_flags.is_slack_app_forking_enabled", return_value=flag),
            # Real capture spins up (and synchronously shuts down) a PostHog client,
            # which is slow and tears down connections other tests are still using.
            patch("products.slack_app.backend.analytics.capture_slack_event"),
            patch(f"{_FORK_MODULE}._ephemeral") as ephemeral,
            patch("products.slack_app.backend.api._start_mention_workflow") as start,
            patch(
                "products.slack_app.backend.api.resolve_posthog_user_from_event",
                return_value=self.user,
            ),
            patch("products.slack_app.backend.api.get_slack_email_for_user", return_value=self.user.email),
        ):
            process_slack_app_fork_thread_payload(payload)
        return start, ephemeral

    def test_forks_to_dm_with_source_thread_as_context(self):
        slack = self._slack_mock()

        start, ephemeral = self._run(self._payload(), slack)

        start.assert_called_once()
        event, integration, slack_team_id, event_id = start.call_args.args
        kwargs = start.call_args.kwargs
        # The run answers in the DM…
        assert event["channel"] == "D_ALICE"
        assert event["thread_ts"] == "999.1"
        assert event["text"] == FORK_DEFAULT_PROMPT
        # …while reading its context from the channel thread that was forked. The
        # message's own ts is ignored in favour of its thread root.
        assert kwargs["fork_source_channel"] == "C_SOURCE"
        assert kwargs["fork_source_thread_ts"] == "111.1"
        assert integration == self.integration
        assert slack_team_id == "T_SLACK"

        # Nothing may be posted into the source channel — the whole point is privacy.
        posted_channels = [c.kwargs["channel"] for c in slack.client.chat_postMessage.call_args_list]
        assert posted_channels == ["U_ALICE"]
        ephemeral.assert_called_once()

    def test_typed_question_becomes_the_runs_request(self):
        start, _ = self._run(self._payload(fork_prompt="why is the retry loop double-counting?"), self._slack_mock())

        assert start.call_args.args[0]["text"] == "why is the retry loop double-counting?"

    def test_without_a_question_the_run_opens_with_the_default_ask(self):
        start, _ = self._run(self._payload(), self._slack_mock())

        assert start.call_args.args[0]["text"] == FORK_DEFAULT_PROMPT

    def test_inherits_repository_from_forked_threads_task(self):
        from django.apps import apps

        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="posthog/posthog",
        )
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C_SOURCE",
            thread_ts="111.1",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U_BOB",
        )

        start, _ = self._run(self._payload(), self._slack_mock())

        assert start.call_args.kwargs["fork_repository"] == "posthog/posthog"

    def test_no_mapping_leaves_repository_to_the_cascade(self):
        start, _ = self._run(self._payload(), self._slack_mock())

        assert start.call_args.kwargs["fork_repository"] is None

    def test_ext_shared_source_is_inherited_by_the_dm_run(self):
        """A DM is never ext-shared, so without inheritance a fork would launder
        Slack Connect content past the approval gate on customer-facing writes."""
        from products.slack_app.backend.models import SlackChannel

        SlackChannel.objects.create(
            slack_workspace_id="T_SLACK",
            slack_channel_id="C_SOURCE",
            approved_at="2026-01-01T00:00:00Z",
        )

        start, _ = self._run(self._payload(), self._slack_mock(ext_shared=True))

        assert start.call_args.kwargs["is_ext_shared_channel"] is True

    @parameterized.expand(
        [
            ("flag_off", {"flag": False}, {}),
            ("ext_shared_unapproved", {}, {"ext_shared": True}),
            ("bot_not_in_channel", {}, {"readable": False}),
        ]
    )
    def test_refusals_create_no_run(self, _name, run_kwargs, slack_kwargs):
        slack = self._slack_mock(**slack_kwargs)

        start, _ = self._run(self._payload(), slack, **run_kwargs)

        start.assert_not_called()
        slack.client.chat_postMessage.assert_not_called()

    def test_flag_off_stays_silent(self):
        """A workspace outside the rollout should not learn the feature exists."""
        _, ephemeral = self._run(self._payload(), self._slack_mock(), flag=False)

        ephemeral.assert_not_called()

    @parameterized.expand(
        [
            ("no_channel", {"channel": {}}),
            ("no_message", {"message": {}}),
            ("no_user", {"user": {}}),
            ("no_team", {"team": {}}),
        ]
    )
    def test_malformed_payload_is_dropped(self, _name, overrides):
        slack = self._slack_mock()

        start, _ = self._run(self._payload(**overrides), slack)

        start.assert_not_called()


class TestForkThreadInteractivityDispatch(TestCase):
    """The webhook must recognise the shortcut and hand it straight to Temporal —
    Slack drops the interaction if the ack takes longer than three seconds, so
    nothing but dispatch may happen inline."""

    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-test-secret"
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        Integration.objects.create(team=self.team, kind="slack", integration_id="T12345", config={})

    def _post(self, payload: dict):
        body_str = f"payload={json.dumps({'team': {'id': 'T12345'}, **payload})}"
        signed = sign_slack_request(body_str.encode(), self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signed.signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=signed.timestamp,
        )

    def _shortcut(self, **overrides) -> dict:
        payload = {
            "type": "message_action",
            "callback_id": FORK_THREAD_CALLBACK_ID,
            "user": {"id": "U_ALICE"},
            "channel": {"id": "C_SOURCE"},
            "message": {"ts": "111.2", "thread_ts": "111.1"},
        }
        payload.update(overrides)
        return payload

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    @patch("products.slack_app.backend.api.sync_connect")
    def test_shortcut_dispatches_workflow_keyed_on_the_forked_thread(self, mock_connect, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_client = MagicMock()
        mock_connect.return_value = mock_client

        response = self._post(self._shortcut())

        assert response.status_code == 200
        mock_client.start_workflow.assert_called_once()
        # Keyed on the thread root, not the clicked message: forking two replies in
        # the same discussion is the same fork, and must not open two DM threads.
        assert mock_client.start_workflow.call_args.kwargs["id"] == "slack-app-fork-thread:T12345:U_ALICE:111.1"

    @parameterized.expand(
        [
            ("other_callback_id", {"callback_id": "something_else"}),
            ("no_callback_id", {"callback_id": None}),
        ]
    )
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    @patch("products.slack_app.backend.api.sync_connect")
    def test_unrelated_message_action_is_ignored(self, _name, overrides, mock_connect, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        response = self._post(self._shortcut(**overrides))

        assert response.status_code == 200
        mock_connect.assert_not_called()

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    @patch("products.slack_app.backend.api.sync_connect")
    def test_shortcut_from_an_unknown_workspace_is_not_claimed(self, mock_connect, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        body_str = f"payload={json.dumps({**self._shortcut(), 'team': {'id': 'T_UNKNOWN'}})}"
        signed = sign_slack_request(body_str.encode(), self.signing_secret)

        response = self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signed.signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=signed.timestamp,
        )

        assert response.status_code == 200
        mock_connect.assert_not_called()


class TestForkCommandParsing(TestCase):
    def test_fork_parses_from_both_surfaces(self):
        from products.slack_app.backend.api import parse_rules_command

        for text in ("fork", "FORK", "<@UBOT> fork"):
            parsed = parse_rules_command(text)
            assert parsed is not None, text
            assert parsed.action == "fork", text

    def test_trailing_text_becomes_the_forked_runs_question(self):
        from products.slack_app.backend.api import parse_rules_command

        parsed = parse_rules_command("fork why does the retry loop double-count?")
        assert parsed is not None
        assert parsed.action == "fork"
        assert parsed.fork_prompt == "why does the retry loop double-count?"

    def test_bare_fork_carries_no_question(self):
        # `None` is what makes the activity fall back to the default "catch me up" ask.
        from products.slack_app.backend.api import parse_rules_command

        parsed = parse_rules_command("fork")
        assert parsed is not None and parsed.fork_prompt is None

    def test_a_word_merely_starting_with_fork_is_not_the_command(self):
        from products.slack_app.backend.api import parse_rules_command

        assert parse_rules_command("forking hell") is None


class TestForkButtonDispatch(TestCase):
    """The button under a finished reply is the no-configuration trigger: it needs no
    manifest change, and a `block_actions` payload already carries the channel, the
    thread the reply sits in, and a private `response_url`."""

    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-test-secret"
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T12345", config={})

    def _click(self, integration_id: int, team_id: str = "T12345"):
        from products.slack_app.backend.services.slack_messages import FORK_THREAD_ACTION_ID

        payload = {
            "type": "block_actions",
            "team": {"id": team_id},
            "user": {"id": "U_ALICE"},
            "channel": {"id": "C_SOURCE"},
            "message": {"ts": "222.1", "thread_ts": "111.1"},
            "response_url": "https://hooks.slack.test/resp",
            "actions": [
                {
                    "action_id": FORK_THREAD_ACTION_ID,
                    "value": json.dumps({"integration_id": integration_id}),
                }
            ],
        }
        body_str = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body_str.encode(), self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signed.signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=signed.timestamp,
        )

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    @patch("products.slack_app.backend.api.sync_connect")
    def test_click_dispatches_keyed_on_the_thread_the_reply_sits_in(self, mock_connect, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_client = MagicMock()
        mock_connect.return_value = mock_client

        response = self._click(self.integration.id)

        assert response.status_code == 200
        mock_client.start_workflow.assert_called_once()
        # Keyed on the source thread, not the bot reply the button is attached to, so
        # clicking the button on two replies in one thread is one fork.
        assert mock_client.start_workflow.call_args.kwargs["id"] == "slack-app-fork-thread:T12345:U_ALICE:111.1"

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    @patch("products.slack_app.backend.api.sync_connect")
    def test_click_from_an_unknown_workspace_is_not_claimed(self, mock_connect, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        response = self._click(self.integration.id, team_id="T_UNKNOWN")

        assert response.status_code == 200
        mock_connect.assert_not_called()
