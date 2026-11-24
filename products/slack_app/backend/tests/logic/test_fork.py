import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.feature_flags import ASSISTANT_REQUIRED_SCOPES
from products.slack_app.backend.logic.fork.start import start_fork
from products.slack_app.backend.tests.helpers import sign_slack_request

_FORK_MODULE = "products.slack_app.backend.logic.fork.start"


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
            "type": "block_actions",
            "user": {"id": "U_ALICE"},
            "team": {"id": "T_SLACK"},
            "channel": {"id": "C_SOURCE"},
            "message": {"ts": "111.2", "thread_ts": "111.1", "text": "the discussion"},
            "response_url": "https://hooks.slack.test/resp",
        }
        payload.update(overrides)
        return payload

    def _slack_mock(
        self, *, ext_shared: bool = False, private: bool = False, readable: bool = True, joinable: bool = True
    ) -> MagicMock:
        slack = MagicMock()
        slack.client.conversations_info.return_value = {"channel": {"is_ext_shared": ext_shared, "is_private": private}}
        slack.client.conversations_join.return_value = {"ok": joinable}
        if readable:
            slack.client.conversations_replies.return_value = {
                "messages": [{"ts": "111.1", "text": "The retry loop double-counts on 429s\nmore detail here"}]
            }
        else:
            slack.client.conversations_replies.side_effect = Exception("not_in_channel")
        slack.client.chat_postMessage.side_effect = lambda **kwargs: {
            "channel": "D_ALICE" if kwargs["channel"] == "U_ALICE" else kwargs["channel"],
            "ts": "999.1",
        }
        slack.client.chat_getPermalink.side_effect = lambda **kwargs: {
            "ok": True,
            "permalink": f"https://slack.test/archives/{kwargs['channel']}/p{kwargs['message_ts'].replace('.', '')}",
        }
        return slack

    def _run(self, payload: dict, slack: MagicMock, *, flag: bool = True, mcp: bool = True, target_channel=None):
        """Drive the payload with the Slack client, flag and Slack MCP check stubbed.
        Returns the patched ephemeral poster and the patched mention workflow start."""
        with (
            patch("posthog.models.integration.SlackIntegration", return_value=slack),
            patch("products.slack_app.backend.feature_flags.is_slack_app_forking_enabled", return_value=flag),
            patch("products.mcp_store.backend.facade.api.has_slack_mcp_connected", return_value=mcp),
            # Real capture spins up (and synchronously shuts down) a PostHog client,
            # which is slow and tears down connections other tests are still using.
            patch("products.slack_app.backend.analytics.capture_slack_event"),
            patch(f"{_FORK_MODULE}._ephemeral") as ephemeral,
            patch("products.slack_app.backend.api._start_mention_workflow") as start,
            patch("products.slack_app.backend.api.resolve_posthog_user_from_event", return_value=self.user),
            patch("products.slack_app.backend.api.get_slack_email_for_user", return_value=self.user.email),
        ):
            start_fork(payload, target_channel=target_channel)
        return ephemeral, start

    def test_a_dm_fork_starts_the_run_in_the_dm_and_points_it_at_the_source_thread(self):
        slack = self._slack_mock()

        ephemeral, start = self._run(self._payload(), slack)

        assert slack.client.chat_postMessage.call_args.kwargs["channel"] == "U_ALICE"
        event = start.call_args.args[0]
        assert (event["channel"], event["thread_ts"], event["channel_type"]) == ("D_ALICE", "999.1", "im")
        assert event["user"] == "U_ALICE"
        kwargs = start.call_args.kwargs
        assert kwargs["posthog_user"] == self.user
        assert (kwargs["fork_source_channel"], kwargs["fork_source_thread_ts"]) == ("C_SOURCE", "111.1")
        assert kwargs["fork_source_message_ts"] == "111.2"
        ephemeral.assert_called_once()

    def test_a_channel_fork_starts_the_run_in_the_picked_channel(self):
        slack = self._slack_mock()

        _, start = self._run(self._payload(), slack, target_channel="C_TARGET")

        slack.client.conversations_join.assert_called_once_with(channel="C_TARGET")
        posted = [c.kwargs["channel"] for c in slack.client.chat_postMessage.call_args_list]
        assert posted == ["C_TARGET"]
        event = start.call_args.args[0]
        assert (event["channel"], event["thread_ts"], event["channel_type"]) == ("C_TARGET", "999.1", "channel")
        assert start.call_args.kwargs["fork_source_channel"] == "C_SOURCE"
        # The channel did not see the click, so the seed says who forked.
        footer = slack.client.chat_postMessage.call_args.kwargs["blocks"][1]["elements"][0]["text"]
        assert footer.startswith("Forked by <@U_ALICE> · ")

    def test_the_seed_links_the_forked_message_and_the_thread(self):
        slack = self._slack_mock()

        self._run(self._payload(), slack)

        blocks = slack.client.chat_postMessage.call_args.kwargs["blocks"]
        # The reply the menu hung off (111.2), not the thread root (111.1): that is where the reader forked.
        assert (
            "Continuing from <https://slack.test/archives/C_SOURCE/p1112|this message> in <#C_SOURCE>"
            in blocks[0]["text"]["text"]
        )
        assert blocks[1]["type"] == "context"
        footer = blocks[1]["elements"][0]["text"]
        assert "<https://slack.test/archives/C_SOURCE/p1111|Open thread>" in footer
        assert "Forked by" not in footer

    @parameterized.expand(
        [
            (
                "first_line",
                {"ts": "111.1", "text": "The retry loop double-counts on 429s\nmore detail here"},
                "The retry loop double-counts on 429s",
            ),
            (
                "leading_mention_dropped",
                {"ts": "111.1", "text": "<@UBOT123> give me a joke please"},
                "give me a joke please",
            ),
            ("no_text", {"ts": "111.1"}, "Slack thread"),
            ("unreadable", None, "Slack thread"),
        ]
    )
    def test_the_seed_and_the_task_are_titled_after_the_opening_message(self, _name, root, title):
        slack = self._slack_mock(readable=root is not None)
        if root is not None:
            slack.client.conversations_replies.return_value = {"messages": [root]}

        _, start = self._run(self._payload(), slack)

        section = slack.client.chat_postMessage.call_args.kwargs["blocks"][0]["text"]["text"]
        assert section.startswith(f":thread: *{title}*\n")
        assert start.call_args.args[0]["text"] == f"Fork: {title}"

    def test_nothing_is_posted_into_the_source_channel(self):
        slack = self._slack_mock()

        self._run(self._payload(), slack)

        posted = [c.kwargs["channel"] for c in slack.client.chat_postMessage.call_args_list]
        assert posted == ["U_ALICE"]

    def test_carries_the_forked_threads_task_and_links_it(self):
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
        slack = self._slack_mock()

        _, start = self._run(self._payload(), slack)

        assert start.call_args.kwargs["fork_source_task_id"] == str(task.id)
        origin = slack.client.chat_postMessage.call_args.kwargs["blocks"][1]["elements"][0]["text"]
        assert f"/tasks/{task.id}|Original task>" in origin

    def test_ext_shared_source_is_inherited_by_the_dm_run(self):
        from products.slack_app.backend.models import SlackChannel

        SlackChannel.objects.create(
            slack_workspace_id="T_SLACK",
            slack_channel_id="C_SOURCE",
            approved_at="2026-01-01T00:00:00Z",
        )

        _, start = self._run(self._payload(), self._slack_mock(ext_shared=True))

        assert start.call_args.kwargs["is_ext_shared_channel"] is True

    @parameterized.expand(
        [
            ("flag_off", {"flag": False}, {}),
            ("no_slack_mcp", {"mcp": False}, {}),
            ("ext_shared_unapproved", {}, {"ext_shared": True}),
            ("private_source_to_channel", {"target_channel": "C_TARGET"}, {"private": True}),
            ("bot_cannot_join_target", {"target_channel": "C_TARGET"}, {"joinable": False}),
        ]
    )
    def test_refusals_start_no_run(self, _name, run_kwargs, slack_kwargs):
        slack = self._slack_mock(**slack_kwargs)

        _, start = self._run(self._payload(), slack, **run_kwargs)

        slack.client.chat_postMessage.assert_not_called()
        start.assert_not_called()

    def test_a_dm_source_cannot_be_forked_to_a_channel(self):
        slack = self._slack_mock()

        _, start = self._run(self._payload(channel={"id": "D_SOURCE"}), slack, target_channel="C_TARGET")

        start.assert_not_called()
        slack.client.conversations_join.assert_not_called()

    def test_flag_off_stays_silent(self):
        ephemeral, _ = self._run(self._payload(), self._slack_mock(), flag=False)

        ephemeral.assert_not_called()

    def test_missing_slack_mcp_links_to_where_to_connect_it(self):
        ephemeral, _ = self._run(self._payload(), self._slack_mock(), mcp=False)

        assert f"/project/{self.team.id}/mcp-servers|" in ephemeral.call_args.args[1]

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

        _, start = self._run(self._payload(**overrides), slack)

        slack.client.chat_postMessage.assert_not_called()
        start.assert_not_called()


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

    def _post(self, payload: dict):
        body_str = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body_str.encode(), self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signed.signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=signed.timestamp,
        )

    def _click(self, integration_id: int, team_id: str = "T12345", target: str | None = None):
        from products.slack_app.backend.logic.fork.menu import FORK_THREAD_ACTION_ID

        value: dict = {"integration_id": integration_id}
        if target:
            value["target"] = target
        payload = {
            "type": "block_actions",
            "team": {"id": team_id},
            "user": {"id": "U_ALICE"},
            "channel": {"id": "C_SOURCE"},
            "message": {"ts": "222.1", "thread_ts": "111.1"},
            "response_url": "https://hooks.slack.test/resp",
            "trigger_id": "trigger-1",
            "actions": [
                {
                    "type": "overflow",
                    "action_id": FORK_THREAD_ACTION_ID,
                    # An overflow reports the chosen entry under `selected_option`, not `value`.
                    "selected_option": {
                        "text": {"type": "plain_text", "text": "Fork to DM"},
                        "value": json.dumps(value),
                    },
                }
            ],
        }
        return self._post(payload)

    @parameterized.expand([("current_menu", "dm"), ("menu_from_before_the_channel_option", None)])
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    @patch("products.slack_app.backend.logic.fork.interactivity.sync_connect")
    def test_click_dispatches_keyed_on_the_thread_the_reply_sits_in(self, _name, target, mock_connect, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_client = MagicMock()
        mock_connect.return_value = mock_client

        response = self._click(self.integration.id, target=target)

        assert response.status_code == 200
        mock_client.start_workflow.assert_called_once()
        # Keyed on the source thread, not the bot reply the button is attached to, so
        # clicking the button on two replies in one thread is one fork.
        assert mock_client.start_workflow.call_args.kwargs["id"] == "slack-app-fork-thread:T12345:U_ALICE:111.1"
        assert mock_client.start_workflow.call_args.args[1].target_channel is None

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    @patch("products.slack_app.backend.logic.fork.interactivity.sync_connect")
    @patch("products.slack_app.backend.logic.fork.interactivity.SlackIntegration")
    def test_channel_option_opens_the_picker_and_its_submit_forks_there(self, mock_slack, mock_connect, mock_config):
        from products.slack_app.backend.logic.fork.channel_picker import FORK_CHANNEL_MODAL_CALLBACK_ID

        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_client = MagicMock()
        mock_connect.return_value = mock_client

        self._click(self.integration.id, target="channel")

        mock_client.start_workflow.assert_not_called()
        view = mock_slack.return_value.client.views_open.call_args.kwargs["view"]
        assert mock_slack.return_value.client.views_open.call_args.kwargs["trigger_id"] == "trigger-1"
        assert view["blocks"][0]["element"]["filter"]["include"] == ["public"]

        response = self._post(
            {
                "type": "view_submission",
                "team": {"id": "T12345"},
                "user": {"id": "U_ALICE"},
                "view": {
                    "callback_id": FORK_CHANNEL_MODAL_CALLBACK_ID,
                    "private_metadata": view["private_metadata"],
                    "state": {
                        "values": {"fork_channel": {"fork_channel_select": {"selected_conversation": "C_TARGET"}}}
                    },
                },
            }
        )

        assert response.status_code == 200
        call = mock_client.start_workflow.call_args
        assert call.kwargs["id"] == "slack-app-fork-thread:T12345:U_ALICE:111.1:C_TARGET"
        inputs = call.args[1]
        assert inputs.target_channel == "C_TARGET"
        assert inputs.payload["channel"] == {"id": "C_SOURCE"}
        assert inputs.payload["message"] == {"ts": "222.1", "thread_ts": "111.1"}

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    @patch("products.slack_app.backend.logic.fork.interactivity.sync_connect")
    def test_click_from_an_unknown_workspace_is_not_claimed(self, mock_connect, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        response = self._click(self.integration.id, team_id="T_UNKNOWN")

        assert response.status_code == 200
        mock_connect.assert_not_called()


class TestForkMenuBlock(SimpleTestCase):
    def test_menu_is_a_bare_overflow_element_carrying_the_integration(self):
        # Bare, not wrapped in an `actions` block, so it can be the footer's accessory
        # and share its line. The integration in the option value is what lets the
        # cross-region interactivity router claim the click.
        from products.slack_app.backend.logic.fork.menu import FORK_THREAD_ACTION_ID, fork_menu_element

        element = fork_menu_element(42)

        assert element["type"] == "overflow"
        assert element["action_id"] == FORK_THREAD_ACTION_ID
        assert [option["text"]["text"] for option in element["options"]] == ["Fork to DM", "Fork to channel"]
        assert all(json.loads(option["value"])["integration_id"] == 42 for option in element["options"])
