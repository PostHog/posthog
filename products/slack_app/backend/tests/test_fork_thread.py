import json

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.fork import process_slack_app_fork_thread_payload

from products.slack_app.backend.feature_flags import ASSISTANT_REQUIRED_SCOPES
from products.slack_app.backend.services.slack_fork_context import PendingFork, get_pending_fork, store_pending_fork
from products.slack_app.backend.tests.helpers import sign_slack_request

_FORK_MODULE = "posthog.temporal.ai.slack_app.activities.fork"


class TestForkThreadPayload(TestCase):
    def setUp(self):
        cache.clear()
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
            "type": "block_actions",
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
            slack.client.conversations_replies.return_value = {
                "messages": [{"ts": "111.1", "text": "The retry loop double-counts on 429s\nmore detail here"}]
            }
        else:
            slack.client.conversations_replies.side_effect = Exception("not_in_channel")
        slack.client.chat_postMessage.return_value = {"channel": "D_ALICE", "ts": "999.1"}
        slack.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.test/archives/C_SOURCE/p111",
        }
        return slack

    def _run(self, payload: dict, slack: MagicMock, *, flag: bool = True):
        """Drive the payload with the Slack client and flag stubbed, returning the
        patched ephemeral poster. Nothing runs at fork time — the DM asks first — so
        assertions are on what was posted and what was parked."""
        with (
            patch("posthog.models.integration.SlackIntegration", return_value=slack),
            patch("products.slack_app.backend.feature_flags.is_slack_app_forking_enabled", return_value=flag),
            # Real capture spins up (and synchronously shuts down) a PostHog client,
            # which is slow and tears down connections other tests are still using.
            patch("products.slack_app.backend.analytics.capture_slack_event"),
            patch(f"{_FORK_MODULE}._ephemeral") as ephemeral,
            patch("products.slack_app.backend.api.resolve_posthog_user_from_event", return_value=self.user),
            patch("products.slack_app.backend.api.get_slack_email_for_user", return_value=self.user.email),
        ):
            process_slack_app_fork_thread_payload(payload)
        return ephemeral

    def test_a_fork_asks_instead_of_running(self):
        # The menu has nowhere to type a question, so guessing at one would spend a
        # sandbox run on an ask the user never made.
        slack = self._slack_mock()

        ephemeral = self._run(self._payload(), slack)

        seed = slack.client.chat_postMessage.call_args
        assert seed.kwargs["channel"] == "U_ALICE"
        assert "What do you want to dig into?" in seed.kwargs["text"]
        ephemeral.assert_called_once()

    def test_the_seed_is_titled_after_the_thread_and_links_back_to_it(self):
        slack = self._slack_mock()

        self._run(self._payload(), slack)

        blocks = slack.client.chat_postMessage.call_args.kwargs["blocks"]
        # No task exists yet — the run waits for the user's answer — so the title comes
        # from the message that opened the forked thread, first line only.
        assert ":thread: *The retry loop double-counts on 429s*" in blocks[0]["text"]["text"]
        assert "more detail here" not in blocks[0]["text"]["text"]
        # The origin is muted, under the title, the way a footer reads.
        assert blocks[1]["type"] == "context"
        origin = blocks[1]["elements"][0]["text"]
        assert "Fork of <https://slack.test/archives/C_SOURCE/p111|this thread>" in origin
        assert "<#C_SOURCE>" in origin

    def test_a_thread_opening_with_no_text_still_gets_a_title(self):
        # Threads that open with a file or an image have nothing to name them after.
        slack = self._slack_mock()
        slack.client.conversations_replies.return_value = {"messages": [{"ts": "111.1"}]}

        self._run(self._payload(), slack)

        blocks = slack.client.chat_postMessage.call_args.kwargs["blocks"]
        assert ":thread: *Slack thread*" in blocks[0]["text"]["text"]

    def test_nothing_is_posted_into_the_source_channel(self):
        # The whole point is asking without an audience. Only the DM may be posted to;
        # the acknowledgement in the thread is ephemeral.
        slack = self._slack_mock()

        self._run(self._payload(), slack)

        posted = [c.kwargs["channel"] for c in slack.client.chat_postMessage.call_args_list]
        assert posted == ["U_ALICE"]

    def test_carries_the_forked_threads_task_but_never_its_repository(self):
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

        self._run(self._payload(), self._slack_mock())

        parked = get_pending_fork(self.integration.id, "D_ALICE", "999.1")
        assert parked is not None
        assert parked.task_id == str(task.id)
        # The repository stays behind on purpose: the source task's repo was resolved
        # against the *original* mentioner's access, and carrying it over would let the
        # forker skip their own authorization gate in the cascade.
        assert not hasattr(parked, "repository")

    def test_no_mapping_carries_no_task(self):
        # Forking a thread the agent has never worked in has no task to inherit from.
        self._run(self._payload(), self._slack_mock())

        parked = get_pending_fork(self.integration.id, "D_ALICE", "999.1")
        assert parked is not None
        assert parked.task_id is None

    def test_ext_shared_source_is_inherited_by_the_dm_run(self):
        """A DM is never ext-shared, so without inheritance a fork would launder
        Slack Connect content past the approval gate on customer-facing writes."""
        from products.slack_app.backend.models import SlackChannel

        SlackChannel.objects.create(
            slack_workspace_id="T_SLACK",
            slack_channel_id="C_SOURCE",
            approved_at="2026-01-01T00:00:00Z",
        )

        self._run(self._payload(), self._slack_mock(ext_shared=True))

        parked = get_pending_fork(self.integration.id, "D_ALICE", "999.1")
        assert parked is not None and parked.is_ext_shared is True

    @parameterized.expand(
        [
            ("flag_off", {"flag": False}, {}),
            ("ext_shared_unapproved", {}, {"ext_shared": True}),
            ("bot_not_in_channel", {}, {"readable": False}),
        ]
    )
    def test_refusals_open_no_dm(self, _name, run_kwargs, slack_kwargs):
        slack = self._slack_mock(**slack_kwargs)

        self._run(self._payload(), slack, **run_kwargs)

        slack.client.chat_postMessage.assert_not_called()
        assert get_pending_fork(self.integration.id, "D_ALICE", "999.1") is None

    def test_flag_off_stays_silent(self):
        """A workspace outside the rollout should not learn the feature exists."""
        ephemeral = self._run(self._payload(), self._slack_mock(), flag=False)

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

        self._run(self._payload(**overrides), slack)

        slack.client.chat_postMessage.assert_not_called()


class TestForkMenuDispatch(TestCase):
    """The menu under a finished reply needs no Slack configuration: a `block_actions`
    payload already carries the channel, the thread the reply sits in, and a private
    `response_url`."""

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
                    "type": "overflow",
                    "action_id": FORK_THREAD_ACTION_ID,
                    # An overflow reports the chosen entry under `selected_option`, not `value`.
                    "selected_option": {
                        "text": {"type": "plain_text", "text": "Fork to DM"},
                        "value": json.dumps({"integration_id": integration_id, "option": "fork_to_dm"}),
                    },
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


class TestForkMenuBlock(TestCase):
    def test_menu_is_a_bare_overflow_element_carrying_the_integration(self):
        # Bare, not wrapped in an `actions` block, so it can be the footer's accessory
        # and share its line. The integration in the option value is what lets the
        # cross-region interactivity router claim the click.
        from products.slack_app.backend.services.slack_messages import FORK_THREAD_ACTION_ID, fork_menu_element

        element = fork_menu_element(42)

        assert element["type"] == "overflow"
        assert element["action_id"] == FORK_THREAD_ACTION_ID
        assert len(element["options"]) == 1
        assert element["options"][0]["text"]["text"] == "Fork to DM"
        assert json.loads(element["options"][0]["value"])["integration_id"] == 42


class TestPendingForkHandoff(TestCase):
    """The reply to "what do you want to dig into?" is an ordinary DM message. Only the
    parked pointer says it belongs to a fork, so losing this handoff would quietly answer
    without the thread the user forked — the failure looks like a bad answer, not a bug."""

    def setUp(self):
        cache.clear()
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

    def _reply_in_dm(self):
        from products.slack_app.backend.api import _handle_assistant_dm_message

        event = {"type": "message", "channel": "D_ALICE", "ts": "999.2", "thread_ts": "999.1", "user": "U_ALICE"}
        with (
            patch("products.slack_app.backend.api.SlackIntegration") as slack_cls,
            patch("products.slack_app.backend.api._start_mention_workflow") as start,
        ):
            slack_cls.return_value.missing_scopes.return_value = set()
            _handle_assistant_dm_message(
                event,
                self.integration,
                "T_SLACK",
                None,
                "D_ALICE",
                "999.1",
                posthog_user=self.user,
            )
        return start

    def test_the_reply_runs_against_the_forked_thread_then_forgets_it(self):
        store_pending_fork(
            self.integration.id,
            "D_ALICE",
            "999.1",
            PendingFork(
                source_channel="C_SOURCE",
                source_thread_ts="111.1",
                is_ext_shared=True,
            ),
        )

        start = self._reply_in_dm()

        kwargs = start.call_args.kwargs
        assert kwargs["fork_source_channel"] == "C_SOURCE"
        assert kwargs["fork_source_thread_ts"] == "111.1"
        # Carried across the handoff, so a fork out of a Slack Connect channel keeps its
        # posture even though the DM it lands in is never externally shared.
        assert kwargs["is_ext_shared_channel"] is True
        # Consumed: the run this starts writes a thread mapping, and every later message
        # is a follow-up against that. Re-applying the forked thread would double it up.
        assert get_pending_fork(self.integration.id, "D_ALICE", "999.1") is None

    def test_an_ordinary_dm_carries_no_fork(self):
        start = self._reply_in_dm()

        assert "fork_source_channel" not in start.call_args.kwargs
