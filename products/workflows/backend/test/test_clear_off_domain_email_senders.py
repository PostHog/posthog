from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration

from products.workflows.backend.management.commands.clear_off_domain_email_senders import clear_off_domain_from_email
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

DOMAINS = {1: {"domain": "posthog.com"}, 2: {"domain": "acme.com"}}


class TestClearOffDomainFromEmail(BaseTest):
    """Pure clearing logic — the decision to drop or keep a stored sender address."""

    @parameterized.expand(
        [
            ("off every selected domain", {"integrationId": 1, "email": "default@example.com"}, True),
            ("on the selected domain", {"integrationId": 1, "email": "sales@posthog.com"}, False),
            ("on one of several senders", {"integrationIds": [1, 2], "email": "sales@posthog.com"}, False),
            ("off all of several senders", {"integrationIds": [1, 2], "email": "x@example.com"}, True),
            ("templated address", {"integrationId": 1, "email": "{{ event.properties.sender }}"}, False),
            ("empty address", {"integrationId": 1, "email": ""}, False),
            ("no override", {"integrationId": 1}, False),
            ("unresolvable integration", {"integrationId": 99, "email": "default@example.com"}, False),
        ]
    )
    def test_clears_only_off_domain_literals(self, _name: str, from_value: dict, expect_cleared: bool) -> None:
        original = dict(from_value)
        cleared = clear_off_domain_from_email(from_value, DOMAINS)
        assert cleared is expect_cleared
        if expect_cleared:
            assert "email" not in from_value
        else:
            assert from_value == original


class TestClearOffDomainEmailSendersCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team, kind="email", integration_id="hi@posthog.com", config={"domain": "posthog.com"}
        )

    def _action(self, email: str) -> dict:
        return {
            "id": "action_function_email_1",
            "type": "function_email",
            "config": {
                "inputs": {
                    "email": {
                        "templating": "liquid",
                        "value": {"from": {"integrationId": self.integration.id, "email": email}, "to": "a@b.com"},
                    }
                },
            },
        }

    def _from(self, flow: HogFlow, *, draft: bool = False) -> dict:
        if draft:
            assert flow.draft is not None
            actions = flow.draft["actions"]
        else:
            actions = flow.actions
        return actions[0]["config"]["inputs"]["email"]["value"]["from"]

    def test_clears_off_domain_sender_in_actions_and_draft(self) -> None:
        flow = HogFlow.objects.create(
            team=self.team,
            name="flow",
            actions=[self._action("default@example.com")],
            draft={"actions": [self._action("default@example.com")]},
            edges=[],
        )

        with (
            patch(
                "products.workflows.backend.management.commands.clear_off_domain_email_senders.reload_hog_flows_on_workers"
            ) as reload,
            self.captureOnCommitCallbacks(execute=True),
        ):
            call_command("clear_off_domain_email_senders", "--team-id", str(self.team.id))

        flow.refresh_from_db()
        assert "email" not in self._from(flow)
        assert "email" not in self._from(flow, draft=True)
        # A live edit must invalidate the worker cache so the placeholder stops rendering.
        reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(flow.id)])

    def test_keeps_on_domain_sender(self) -> None:
        flow = HogFlow.objects.create(
            team=self.team, name="flow", actions=[self._action("sales@posthog.com")], edges=[]
        )

        call_command("clear_off_domain_email_senders", "--team-id", str(self.team.id))

        flow.refresh_from_db()
        assert self._from(flow)["email"] == "sales@posthog.com"

    def test_dry_run_writes_nothing(self) -> None:
        flow = HogFlow.objects.create(
            team=self.team, name="flow", actions=[self._action("default@example.com")], edges=[]
        )

        call_command("clear_off_domain_email_senders", "--team-id", str(self.team.id), "--dry-run")

        flow.refresh_from_db()
        assert self._from(flow)["email"] == "default@example.com"

    def test_does_not_touch_other_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        flow = HogFlow.objects.create(
            team=other_team, name="flow", actions=[self._action("default@example.com")], edges=[]
        )

        call_command("clear_off_domain_email_senders", "--team-id", str(self.team.id))

        flow.refresh_from_db()
        assert self._from(flow)["email"] == "default@example.com"

    @parameterized.expand([("no scope", []), ("both scopes", ["--team-id", "1", "--all-teams"])])
    def test_refuses_an_ambiguous_team_scope(self, _name: str, scope_args: list[str]) -> None:
        with self.assertRaises(CommandError):
            call_command("clear_off_domain_email_senders", *scope_args)
