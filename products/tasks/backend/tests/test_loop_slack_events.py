from typing import ClassVar

from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.redis import get_client

from products.tasks.backend.loop_slack_events import handle_slack_message_for_loops
from products.tasks.backend.models import Loop, LoopTrigger, Task

FIRE_LOOP_PATCH_TARGET = "products.tasks.backend.logic.services.loop_runs.fire_loop"
CHANNEL = "C0ALERTS01"


class TestHandleSlackMessageForLoops(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    owner: ClassVar[User]
    member: ClassVar[User]
    outsider: ClassVar[User]
    integration: ClassVar[Integration]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Loops Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Team A")
        cls.owner = User.objects.create(email="loop-owner@example.com", distinct_id="loop-owner")
        cls.member = User.objects.create(email="teammate@example.com", distinct_id="teammate")
        cls.outsider = User.objects.create(email="outsider@example.com", distinct_id="outsider")
        cls.organization.members.add(cls.owner)
        cls.organization.members.add(cls.member)
        cls.integration = Integration.objects.create(
            team=cls.team,
            kind="slack",
            integration_id="T0WORKSPACE",
            config={},
        )

    def setUp(self):
        super().setUp()
        self._clear_redis_keys()
        self.addCleanup(self._clear_redis_keys)

    def _clear_redis_keys(self):
        client = get_client()
        for pattern in ("loop_slack_events:throttle:*", "loop_slack_events:has_triggers:*"):
            for key in client.scan_iter(pattern):
                client.delete(key)

    def _create_loop(self, team: Team, *, name: str = "Test loop", created_by: User | None = None) -> Loop:
        return Loop.objects.for_team(team.id, canonical=True).create(
            team=team,
            created_by=created_by or self.owner,
            name=name,
            instructions="Do the thing.",
            runtime_adapter="claude",
            model="claude-sonnet-4-5",
        )

    def _create_slack_trigger(
        self,
        team: Team,
        loop: Loop,
        *,
        slack_integration_id: int,
        channel_ids: list[str] | None = None,
        filters: dict | None = None,
        allowed_posters: dict | None = None,
        enabled: bool = True,
    ) -> LoopTrigger:
        config: dict = {
            "slack_integration_id": slack_integration_id,
            "channel_ids": channel_ids or [CHANNEL],
            "filters": filters if filters is not None else {},
            "allowed_posters": allowed_posters or {"mode": "org_members"},
        }
        return LoopTrigger.objects.for_team(team.id, canonical=True).create(
            team=team,
            loop=loop,
            type=LoopTrigger.TriggerType.SLACK,
            enabled=enabled,
            config=config,
        )

    def _event(self, **overrides) -> dict:
        event: dict = {
            "type": "message",
            "channel": CHANNEL,
            "user": "U0TEAMMATE",
            "ts": "1712345678.000100",
            "text": "Something happened",
        }
        event.update(overrides)
        return event

    def _handle(
        self,
        event: dict,
        *,
        poster_user_id: int | None = None,
        event_id: str = "Ev001",
        integrations: list[Integration] | None = None,
    ) -> int:
        return handle_slack_message_for_loops(
            event=event,
            slack_team_id="T0WORKSPACE",
            event_id=event_id,
            integrations=integrations if integrations is not None else self._workspace_integrations(),
            resolve_poster_user_id=lambda: poster_user_id,
        )

    def _workspace_integrations(self) -> list[Integration]:
        return list(Integration.objects.filter(kind="slack", integration_id="T0WORKSPACE"))

    @parameterized.expand(
        [
            ("matching_keyword", ["incident"], "Incident declared: checkout is down", True),
            ("case_insensitive", ["sev1"], "A SEV1 has been raised", True),
            ("one_of_several", ["outage", "incident"], "Incident declared", True),
            ("no_keyword_matches", ["outage"], "Deploy finished cleanly", False),
            # An empty keywords list means "run on every message in the channel", which is a
            # supported (if broad) configuration — it must not read as "match nothing".
            ("no_keywords_configured", [], "Anything at all", True),
        ]
    )
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_keyword_filter_gates_firing(self, _name, keywords, text, should_fire, mock_fire_loop):
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team, loop, slack_integration_id=self.integration.id, filters={"keywords": keywords}
        )

        self._handle(self._event(text=text), poster_user_id=self.member.id)

        self.assertEqual(mock_fire_loop.called, should_fire)

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_keywords_match_text_carried_in_blocks_and_attachments(self, mock_fire_loop):
        # Alerting apps post their content as Block Kit blocks and attachments with an empty
        # top-level `text`. Matching only `event["text"]` would mean a keyword trigger aimed at
        # an alert bot never fires, which is the main thing this trigger type exists for.
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team, loop, slack_integration_id=self.integration.id, filters={"keywords": ["sev1"]}
        )
        event = self._event(
            text="",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "A SEV1 incident was declared"}}],
            attachments=[{"fallback": "unrelated"}],
        )

        self._handle(event, poster_user_id=self.member.id)

        self.assertTrue(mock_fire_loop.called)

    @parameterized.expand(
        [
            ("org_members_admits_a_member", {"mode": "org_members"}, "member", True),
            ("org_members_refuses_a_non_member", {"mode": "org_members"}, "outsider", False),
            ("org_members_refuses_an_unresolvable_poster", {"mode": "org_members"}, None, False),
            ("loop_owner_admits_the_owner", {"mode": "loop_owner"}, "owner", True),
            ("loop_owner_refuses_a_teammate", {"mode": "loop_owner"}, "member", False),
        ]
    )
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_poster_gate_decides_who_can_fire(self, _name, allowed_posters, poster, should_fire, mock_fire_loop):
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team, loop, slack_integration_id=self.integration.id, allowed_posters=allowed_posters
        )
        poster_user_id = None if poster is None else getattr(self, poster).id

        self._handle(self._event(), poster_user_id=poster_user_id)

        self.assertEqual(mock_fire_loop.called, should_fire)

    @parameterized.expand(
        [
            ("listed_user", {"user": "U0ONCALL"}, ["U0ONCALL"], True),
            ("listed_bot_id", {"bot_id": "B0INCIDENT", "user": None}, ["B0INCIDENT"], True),
            ("listed_bot_profile_id", {"bot_profile": {"id": "B0INCIDENT"}}, ["B0INCIDENT"], True),
            ("unlisted_author", {"bot_id": "B0SOMETHINGELSE"}, ["B0INCIDENT"], False),
        ]
    )
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_slack_user_ids_mode_matches_any_author_identity(self, _name, author, allowed, should_fire, mock_fire_loop):
        # An alerting app posts under a bot ID with no `user` at all, so an allowlist that only
        # matched `event["user"]` could never admit the case this mode exists for.
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team,
            loop,
            slack_integration_id=self.integration.id,
            allowed_posters={"mode": "slack_user_ids", "slack_user_ids": allowed},
        )

        self._handle(self._event(**author), poster_user_id=None)

        self.assertEqual(mock_fire_loop.called, should_fire)

    @parameterized.expand(
        [
            ("listed_bot_id", {"bot_id": "B0ALERTS"}, True),
            ("listed_app_id", {"app_id": "A0ALERTS"}, True),
            ("unlisted_bot", {"bot_id": "B0OTHER"}, False),
        ]
    )
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_allowed_bot_ids_fire_alongside_the_human_mode(self, _name, author, should_fire, mock_fire_loop):
        # The human modes reject every app author, so the bot allowlist has to be consulted
        # before that rejection or "any org member, plus these bots" can never fire for a bot.
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team,
            loop,
            slack_integration_id=self.integration.id,
            allowed_posters={"mode": "org_members", "allowed_bot_ids": ["B0ALERTS", "A0ALERTS"]},
        )

        self._handle(self._event(**author), poster_user_id=None)

        self.assertEqual(mock_fire_loop.called, should_fire)

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_allowed_bot_ids_do_not_widen_the_human_rule(self, mock_fire_loop):
        # The bot list is an additional door, not a bypass: a human the mode's own check
        # refuses must still be refused when a bot list is present.
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team,
            loop,
            slack_integration_id=self.integration.id,
            allowed_posters={"mode": "org_members", "allowed_bot_ids": ["B0ALERTS"]},
        )

        self._handle(self._event(), poster_user_id=None)

        self.assertFalse(mock_fire_loop.called)

    @parameterized.expand([("bot_id", {"bot_id": "B0RELAY"}), ("app_id", {"app_id": "A0RELAY"})])
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_app_authored_messages_cannot_satisfy_the_human_poster_modes(self, _name, author, mock_fire_loop):
        # An app posting on a person's behalf is indistinguishable from that person typing, so a
        # relay app reposting human text must not be able to start a run under that person.
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team, loop, slack_integration_id=self.integration.id, allowed_posters={"mode": "org_members"}
        )

        self._handle(self._event(**author), poster_user_id=self.member.id)

        self.assertFalse(mock_fire_loop.called)

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_org_members_refuses_a_member_of_a_different_connected_org(self, mock_fire_loop):
        # One Slack workspace can be connected to several organizations. Resolving the poster to
        # "a member of some connected org" says nothing about the loop's own project, so the
        # check has to be against that project specifically.
        other_org = Organization.objects.create(name="Other Org")
        other_member = User.objects.create(email="other@example.com", distinct_id="other")
        other_org.members.add(other_member)
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team, loop, slack_integration_id=self.integration.id, allowed_posters={"mode": "org_members"}
        )

        self._handle(self._event(), poster_user_id=other_member.id)

        self.assertFalse(mock_fire_loop.called)

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_only_the_integrations_the_caller_passed_can_fire(self, mock_fire_loop):
        # The caller has already dropped installs that are unhealthy or whose org hasn't opted
        # into the rollout, so matching must not widen back out to the whole workspace.
        loop = self._create_loop(self.team)
        self._create_slack_trigger(self.team, loop, slack_integration_id=self.integration.id)

        self._handle(self._event(), poster_user_id=self.member.id, integrations=[])

        self.assertFalse(mock_fire_loop.called)

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_cross_team_integration_reference_never_fires(self, mock_fire_loop):
        # Team B shares the same Slack workspace and its trigger names Team A's integration row.
        # Matching must scope to the integration's actual owning team, not the config value, or
        # Team B could fire a run against Team A's workspace by typing its id.
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        Integration.objects.create(team=team_b, kind="slack", integration_id="T0WORKSPACE", config={})

        loop_a = self._create_loop(self.team, name="Loop A")
        trigger_a = self._create_slack_trigger(self.team, loop_a, slack_integration_id=self.integration.id)
        loop_b = self._create_loop(team_b, name="Loop B")
        self._create_slack_trigger(team_b, loop_b, slack_integration_id=self.integration.id)

        self._handle(self._event(), poster_user_id=self.member.id)

        self.assertEqual(mock_fire_loop.call_count, 1)
        self.assertEqual(mock_fire_loop.call_args.kwargs["trigger"].id, trigger_a.id)

    @parameterized.expand(
        [
            # A top-level post has no thread yet, so the run opens one under the message itself.
            ("top_level_post", {}, "1712345678.000100"),
            ("reply_in_an_existing_thread", {"thread_ts": "1712340000.000001"}, "1712340000.000001"),
        ]
    )
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_run_reports_into_the_triggering_messages_thread(self, _name, overrides, expected_ts, mock_fire_loop):
        loop = self._create_loop(self.team)
        self._create_slack_trigger(self.team, loop, slack_integration_id=self.integration.id)

        self._handle(self._event(**overrides), poster_user_id=self.member.id)

        target = mock_fire_loop.call_args.kwargs["slack_thread_target"]
        self.assertEqual(target["thread_ts"], expected_ts)
        self.assertEqual(target["channel"], CHANNEL)
        self.assertEqual(target["integration_id"], self.integration.id)

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_reply_inside_an_existing_agent_thread_does_not_fire(self, mock_fire_loop):
        # Otherwise a loop's own report, posted into the thread it was triggered from, matches
        # the same keyword and re-triggers the loop indefinitely.
        from products.slack_app.backend.models import SlackThreadTaskMapping

        loop = self._create_loop(self.team)
        self._create_slack_trigger(self.team, loop, slack_integration_id=self.integration.id)
        task = Task.objects.create(
            team=self.team, created_by=self.owner, title="Existing run", description="Existing run"
        )
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T0WORKSPACE",
            channel=CHANNEL,
            thread_ts="1712340000.000001",
            task=task,
            task_run=task.create_run(mode="background"),
            mentioning_slack_user_id="U0TEAMMATE",
        )

        self._handle(self._event(thread_ts="1712340000.000001"), poster_user_id=self.member.id)

        self.assertFalse(mock_fire_loop.called)

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_poster_is_not_resolved_when_no_trigger_matches(self, mock_fire_loop):
        # Resolving a Slack user costs a users.info round trip. Paying it before knowing a
        # trigger matched would put that call on every message in the channel.
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team, loop, slack_integration_id=self.integration.id, filters={"keywords": ["incident"]}
        )
        resolve_calls: list[int] = []

        def resolve_poster_user_id() -> int:
            resolve_calls.append(1)
            return self.member.id

        handle_slack_message_for_loops(
            event=self._event(text="deploy finished"),
            slack_team_id="T0WORKSPACE",
            event_id="Ev001",
            integrations=self._workspace_integrations(),
            resolve_poster_user_id=resolve_poster_user_id,
        )

        self.assertEqual(resolve_calls, [])
        self.assertFalse(mock_fire_loop.called)

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_fire_key_falls_back_to_the_message_identity_without_an_event_id(self, mock_fire_loop):
        # An empty fire key would be identical for every message on a trigger, so dedup would
        # swallow all but the very first one.
        loop = self._create_loop(self.team)
        self._create_slack_trigger(self.team, loop, slack_integration_id=self.integration.id)

        self._handle(self._event(), poster_user_id=self.member.id, event_id="")

        self.assertEqual(mock_fire_loop.call_args.kwargs["fire_key"], f"{CHANNEL}:1712345678.000100")

    @parameterized.expand(
        [
            ("matching_condition", [{"path": "subtype", "equals": ["file_share"]}], {"subtype": "file_share"}, True),
            ("non_matching_condition", [{"path": "subtype", "equals": ["file_share"]}], {}, False),
        ]
    )
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_payload_conditions_gate_firing(self, _name, conditions, overrides, should_fire, mock_fire_loop):
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team, loop, slack_integration_id=self.integration.id, filters={"payload": conditions}
        )

        self._handle(self._event(**overrides), poster_user_id=self.member.id)

        self.assertEqual(mock_fire_loop.called, should_fire)

    @parameterized.expand(
        [
            ("wrong_channel", {"channel": "C0OTHER"}),
            ("disabled_trigger", {}),
        ]
    )
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_triggers_outside_their_configured_scope_do_not_fire(self, name, event_overrides, mock_fire_loop):
        loop = self._create_loop(self.team)
        self._create_slack_trigger(
            self.team, loop, slack_integration_id=self.integration.id, enabled=name != "disabled_trigger"
        )

        self._handle(self._event(**event_overrides), poster_user_id=self.member.id)

        self.assertFalse(mock_fire_loop.called)
