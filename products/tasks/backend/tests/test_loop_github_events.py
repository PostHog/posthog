from typing import ClassVar

from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.loop_github_events import handle_github_event_for_loops
from products.tasks.backend.models import Loop, LoopTrigger

FIRE_LOOP_PATCH_TARGET = "products.tasks.backend.logic.services.loop_runs.fire_loop"


class TestHandleGithubEventForLoops(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    integration: ClassVar[Integration]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Loops Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Team A")
        cls.user = User.objects.create(email="loop-owner@example.com", distinct_id="loop-owner")
        cls.integration = Integration.objects.create(
            team=cls.team,
            kind="github",
            integration_id="998877",
            config={},
        )

    def _create_loop(self, team: Team, *, name: str = "Test loop") -> Loop:
        return Loop.objects.for_team(team.id, canonical=True).create(
            team=team,
            created_by=self.user,
            name=name,
            instructions="Do the thing.",
            runtime_adapter="claude",
            model="claude-sonnet-4-5",
        )

    def _create_github_trigger(
        self,
        team: Team,
        loop: Loop,
        *,
        github_integration_id: int,
        repository: str,
        events: list[str],
        filters: dict | None = None,
        enabled: bool = True,
    ) -> LoopTrigger:
        config: dict = {
            "github_integration_id": github_integration_id,
            "repository": repository,
            "events": events,
        }
        if filters is not None:
            config["filters"] = filters
        return LoopTrigger.objects.for_team(team.id, canonical=True).create(
            team=team,
            loop=loop,
            type=LoopTrigger.TriggerType.GITHUB,
            enabled=enabled,
            config=config,
        )

    def _event_payload(
        self,
        event_type: str,
        *,
        installation_id: int,
        repository: str,
        action: str | None = None,
        ref: str | None = None,
    ) -> dict:
        payload: dict = {
            "installation": {"id": installation_id},
            "repository": {"full_name": repository},
        }
        if action is not None:
            payload["action"] = action
        if event_type == "push":
            payload["ref"] = ref or "refs/heads/main"
        return payload

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_cross_team_integration_reference_never_fires(self, mock_fire_loop):
        # Team B shares the same GitHub installation id as Team A, and its trigger
        # references Team A's own integration row and repo name. The fan-out must
        # scope matching to the integration's actual owning team, not just the
        # config value, or Team B could fire against Team A's repo by typing it.
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        Integration.objects.create(team=team_b, kind="github", integration_id="998877", config={})

        loop_a = self._create_loop(self.team, name="Loop A")
        trigger_a = self._create_github_trigger(
            self.team,
            loop_a,
            github_integration_id=self.integration.id,
            repository="acme/shared-repo",
            events=["push"],
        )

        loop_b = self._create_loop(team_b, name="Loop B")
        self._create_github_trigger(
            team_b,
            loop_b,
            github_integration_id=self.integration.id,
            repository="acme/shared-repo",
            events=["push"],
        )

        handle_github_event_for_loops(
            "push",
            self._event_payload("push", installation_id=998877, repository="acme/shared-repo"),
            delivery_id="del-1",
        )

        mock_fire_loop.assert_called_once()
        self.assertEqual(mock_fire_loop.call_args.kwargs["trigger"].id, trigger_a.id)

    @parameterized.expand(
        [
            ("matches_event_and_action", "pull_request", "opened", "acme/repo", True),
            ("wrong_repository", "pull_request", "opened", "acme/other-repo", False),
            ("event_not_subscribed", "push", None, "acme/repo", False),
            ("action_filtered_out", "pull_request", "closed", "acme/repo", False),
            ("second_subscribed_event_matches", "issues", "opened", "acme/repo", True),
        ]
    )
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_matches_on_integration_repository_event_and_action_filter(
        self, _name, event_type, action, repository, expect_fired, mock_fire_loop
    ):
        loop = self._create_loop(self.team)
        self._create_github_trigger(
            self.team,
            loop,
            github_integration_id=self.integration.id,
            repository="acme/repo",
            events=["pull_request", "issues"],
            filters={"actions": ["opened"]},
        )

        handle_github_event_for_loops(
            event_type,
            self._event_payload(event_type, installation_id=998877, repository=repository, action=action),
            delivery_id="del-matching",
        )

        if expect_fired:
            mock_fire_loop.assert_called_once()
        else:
            mock_fire_loop.assert_not_called()

    @parameterized.expand(
        [
            ("loop_branch_push_excluded", "refs/heads/loop/run-123", False),
            ("normal_branch_push_fires", "refs/heads/main", True),
        ]
    )
    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_self_trigger_exclusion_for_loop_branch_pushes(self, _name, ref, expect_fired, mock_fire_loop):
        loop = self._create_loop(self.team)
        self._create_github_trigger(
            self.team,
            loop,
            github_integration_id=self.integration.id,
            repository="acme/repo",
            events=["push"],
        )

        handle_github_event_for_loops(
            "push",
            self._event_payload("push", installation_id=998877, repository="acme/repo", ref=ref),
            delivery_id="del-self-trigger",
        )

        if expect_fired:
            mock_fire_loop.assert_called_once()
        else:
            mock_fire_loop.assert_not_called()

    @patch(FIRE_LOOP_PATCH_TARGET, autospec=True)
    def test_redelivered_webhook_reuses_the_same_fire_key(self, mock_fire_loop):
        # handle_github_event_for_loops does not dedup deliveries itself: it always
        # calls fire_loop for every match, using the delivery id as fire_key.
        # LoopFire's unique (loop_trigger, fire_key) constraint downstream is what
        # collapses a redelivered webhook into a single fire, and only works if the
        # same delivery id always maps to the same fire_key.
        loop = self._create_loop(self.team)
        self._create_github_trigger(
            self.team,
            loop,
            github_integration_id=self.integration.id,
            repository="acme/repo",
            events=["push"],
        )
        payload = self._event_payload("push", installation_id=998877, repository="acme/repo")

        handle_github_event_for_loops("push", payload, delivery_id="del-redelivered")
        handle_github_event_for_loops("push", payload, delivery_id="del-redelivered")
        handle_github_event_for_loops("push", payload, delivery_id="del-other")

        self.assertEqual(mock_fire_loop.call_count, 3)
        fire_keys = [call.kwargs["fire_key"] for call in mock_fire_loop.call_args_list]
        self.assertEqual(fire_keys, ["del-redelivered", "del-redelivered", "del-other"])
