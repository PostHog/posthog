import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import Team

from products.workflows.backend.management.commands import rewrite_email_asset_url
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

OLD = "https://assets.example.com/projects/0/banner.png"
NEW = "https://assets.example.com/projects/1/banner.png"


def _actions(url: str) -> list[dict]:
    return [
        {
            "id": "action_function_email_1",
            "type": "function_email",
            "config": {
                "template_id": "template-email",
                "inputs": {
                    "email": {
                        "templating": "liquid",
                        "value": {"html": f'<img src="{url}?w=960px" />', "design": {"src": {"url": url}}},
                    }
                },
            },
        }
    ]


class TestRewriteEmailAssetUrl(BaseTest):
    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="other")

    def _flow(self, team: Team, name: str, url: str = OLD) -> HogFlow:
        return HogFlow.objects.create(team=team, name=name, actions=_actions(url), edges=[])

    @parameterized.expand(
        [
            ("no scope", []),
            ("both scopes", ["--team-id", "1", "--all-teams"]),
        ]
    )
    def test_refuses_an_ambiguous_team_scope(self, _name: str, scope_args: list[str]) -> None:
        # Without this guard a run that forgets --team-id rewrites every team's workflows.
        with self.assertRaises(CommandError):
            call_command("rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, *scope_args)

    def test_refuses_a_from_url_contained_in_the_to_url(self) -> None:
        with self.assertRaises(CommandError):
            call_command("rewrite_email_asset_url", "--from-url", OLD, "--to-url", f"{OLD}?v=2", "--team-id", "1")

    @parameterized.expand([("zero", "0"), ("negative", "-1")])
    def test_refuses_a_batch_size_below_one(self, _name: str, batch_size: str) -> None:
        # 0 raises inside range() mid-run; a negative step skips every row while reporting success.
        with self.assertRaises(CommandError):
            call_command(
                "rewrite_email_asset_url",
                "--from-url",
                OLD,
                "--to-url",
                NEW,
                "--team-id",
                "1",
                "--batch-size",
                batch_size,
            )

    def test_a_failed_row_fails_the_command_and_leaves_the_rest_rewritten(self) -> None:
        # A caller reading only the exit code would otherwise treat a partial rewrite as complete.
        good = self._flow(self.team, "good")
        bad = self._flow(self.team, "bad")

        real_rewrite = rewrite_email_asset_url.rewrite_blob

        def fail_for_bad(blob: object, from_url: str, to_url: str) -> tuple[object, int]:
            if isinstance(blob, list) and blob and blob[0].get("id") == "boom":
                raise ValueError("rewrite exploded")
            return real_rewrite(blob, from_url, to_url)

        bad.actions[0]["id"] = "boom"
        bad.save(update_fields=["actions"])

        with patch.object(rewrite_email_asset_url, "rewrite_blob", fail_for_bad):
            with self.assertRaises(CommandError):
                call_command(
                    "rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, "--team-id", str(self.team.id)
                )

        good.refresh_from_db()
        bad.refresh_from_db()
        assert NEW in json.dumps(good.actions)
        assert OLD in json.dumps(bad.actions)

    def test_rewrites_only_the_named_team(self) -> None:
        mine = self._flow(self.team, "mine")
        theirs = self._flow(self.other_team, "theirs")

        call_command("rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, "--team-id", str(self.team.id))

        mine.refresh_from_db()
        theirs.refresh_from_db()
        assert NEW in json.dumps(mine.actions)
        assert OLD not in json.dumps(mine.actions)
        assert OLD in json.dumps(theirs.actions)

    def test_preserves_query_suffixes_and_is_idempotent(self) -> None:
        flow = self._flow(self.team, "mine")

        for _ in range(2):
            call_command("rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, "--team-id", str(self.team.id))

        flow.refresh_from_db()
        assert f"{NEW}?w=960px" in json.dumps(flow.actions)
        assert json.dumps(flow.actions).count(NEW) == 2
