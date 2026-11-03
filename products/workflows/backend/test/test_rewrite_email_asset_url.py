import io
import json
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration

from products.messaging.backend.facade.api import get_template_email_content
from products.messaging.backend.facade.templates import get_template, save_template_fields
from products.messaging.backend.facade.testing import create_message_template_for_test
from products.messaging.backend.facade.transactional_email import make_transactional
from products.workflows.backend.facade.api import set_default_email_sender_if_unset
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
        content = {"email": {"html": f'<img src="{OLD}?w=960px" />'}}
        my_template = create_message_template_for_test(team_id=self.team.id, name="mine", content=content)
        their_template = create_message_template_for_test(team_id=self.other_team.id, name="theirs", content=content)

        call_command("rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, "--team-id", str(self.team.id))

        mine.refresh_from_db()
        theirs.refresh_from_db()
        assert NEW in json.dumps(mine.actions)
        assert OLD not in json.dumps(mine.actions)
        assert OLD in json.dumps(theirs.actions)
        assert get_template_email_content(self.team.id, my_template) == {"html": f'<img src="{NEW}?w=960px" />'}
        assert get_template_email_content(self.other_team.id, their_template) == content["email"]

    def test_rewrites_a_template_draft_that_alone_holds_the_url(self) -> None:
        published = {"email": {"html": "<p>No images yet</p>"}}
        template = create_message_template_for_test(
            team_id=self.team.id,
            name="drafted",
            content=published,
            draft_content={"email": {"html": f'<img src="{OLD}?w=960px" />'}},
        )

        call_command("rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, "--team-id", str(self.team.id))

        row = get_template(self.team.id, template)
        assert row.draft_content == {"email": {"html": f'<img src="{NEW}?w=960px" />'}}
        assert row.content == published

    def test_preserves_query_suffixes_and_is_idempotent(self) -> None:
        flow = self._flow(self.team, "mine")

        for _ in range(2):
            call_command("rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, "--team-id", str(self.team.id))

        flow.refresh_from_db()
        assert f"{NEW}?w=960px" in json.dumps(flow.actions)
        assert json.dumps(flow.actions).count(NEW) == 2

    @parameterized.expand(
        [
            ("default_targets", []),
            ("workflows_named_first", ["--targets", "hog_flows,message_templates"]),
        ]
    )
    def test_a_run_writes_one_new_version_of_a_transactional_templates_workflow(
        self, _name: str, target_args: list[str]
    ) -> None:
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        template = create_message_template_for_test(
            team_id=self.team.id,
            name="Welcome",
            content={"email": {"subject": "Welcome", "html": f'<img src="{OLD}?w=960px" />'}},
        )
        workflow_id = make_transactional(self.team.id, template, user_id=self.user.id, from_integration_id=None)

        for _ in range(2):
            call_command(
                "rewrite_email_asset_url",
                "--from-url",
                OLD,
                "--to-url",
                NEW,
                "--team-id",
                str(self.team.id),
                *target_args,
            )

        workflow = HogFlow.objects.get(id=workflow_id)
        assert workflow.version == 2
        assert NEW in json.dumps(workflow.actions)
        assert OLD not in json.dumps(workflow.actions)

    def test_a_failed_template_leaves_its_workflow_for_a_rerun_to_version(self) -> None:
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        template = create_message_template_for_test(
            team_id=self.team.id,
            name="Welcome",
            content={"email": {"subject": "Welcome", "html": f'<img src="{OLD}?w=960px" />'}},
        )
        workflow_id = make_transactional(self.team.id, template, user_id=self.user.id, from_integration_id=None)
        rewrite = ["rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, "--team-id", str(self.team.id)]

        sender.config = {"verified": False}
        sender.save()
        with self.assertRaises(CommandError):
            call_command(*rewrite)
        stalled = HogFlow.objects.get(id=workflow_id)

        sender.config = {"verified": True}
        sender.save()
        call_command(*rewrite)
        recovered = HogFlow.objects.get(id=workflow_id)

        assert (stalled.version, OLD in json.dumps(stalled.actions)) == (1, True)
        assert (recovered.version, NEW in json.dumps(recovered.actions)) == (2, True)

    @parameterized.expand(
        [
            ("default_run", False, False, NEW),
            ("workflow_id", True, False, NEW),
            ("template_draft", False, True, NEW),
            ("workflow_id_skips_a_template_with_the_url", True, False, OLD),
        ]
    )
    def test_rewrites_a_transactional_workflow_in_place_when_its_template_sync_does_not(
        self, _name: str, by_id: bool, old_draft: bool, template_url: str
    ) -> None:
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        template = create_message_template_for_test(
            team_id=self.team.id,
            name="Welcome",
            content={"email": {"subject": "Welcome", "html": f'<img src="{template_url}?w=960px" />'}},
            draft_content={"email": {"html": f'<img src="{OLD}?w=960px" />'}} if old_draft else None,
        )
        workflow_id = make_transactional(self.team.id, template, user_id=self.user.id, from_integration_id=None)
        drifted = json.loads(json.dumps(HogFlow.objects.get(id=workflow_id).actions).replace(NEW, OLD))
        HogFlow.objects.filter(id=workflow_id).update(actions=drifted)
        id_args = ["--id", str(workflow_id)] if by_id else []

        call_command(
            "rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, "--team-id", str(self.team.id), *id_args
        )

        actions = json.dumps(HogFlow.objects.get(id=workflow_id).actions)
        assert (OLD in actions, NEW in actions) == (False, True)

    def test_rewrites_the_workflow_of_a_template_deleted_during_the_run(self) -> None:
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        template = create_message_template_for_test(
            team_id=self.team.id,
            name="Welcome",
            content={"email": {"subject": "Welcome", "html": f'<img src="{OLD}?w=960px" />'}},
        )
        workflow_id = make_transactional(self.team.id, template, user_id=self.user.id, from_integration_id=None)

        def delete_instead(template_id: UUID, *_args: object, **_kwargs: object) -> int:
            save_template_fields(
                self.team.id, template_id, {"deleted": True}, user_id=None, require_workflow_editor=lambda _: None
            )
            return 0

        with patch.object(rewrite_email_asset_url, "rewrite_template_content", side_effect=delete_instead):
            call_command("rewrite_email_asset_url", "--from-url", OLD, "--to-url", NEW, "--team-id", str(self.team.id))

        actions = json.dumps(HogFlow.objects.get(id=workflow_id).actions)
        assert (OLD in actions, NEW in actions) == (False, True)

    def test_keeps_a_workflow_on_its_template_when_a_save_puts_the_old_url_back_mid_run(self) -> None:
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        old_content = {"email": {"subject": "Welcome", "html": f'<img src="{OLD}?w=960px" />'}}
        template_id = create_message_template_for_test(team_id=self.team.id, name="Welcome", content=old_content)
        workflow_id = make_transactional(self.team.id, template_id, user_id=self.user.id, from_integration_id=None)
        HogFlow.objects.filter(id=workflow_id).update(draft={"actions": _actions(OLD)})
        team_id = self.team.id

        class SaveWhenWorkflowPassStarts(io.StringIO):
            saved = False

            def write(self, text: str) -> int:
                if text.startswith("hog_flows:") and not self.saved:
                    self.saved = True
                    save_template_fields(
                        team_id,
                        template_id,
                        {"content": old_content},
                        user_id=None,
                        require_workflow_editor=lambda _: None,
                    )
                return super().write(text)

        call_command(
            "rewrite_email_asset_url",
            "--from-url",
            OLD,
            "--to-url",
            NEW,
            "--team-id",
            str(self.team.id),
            stdout=SaveWhenWorkflowPassStarts(),
        )

        workflow = HogFlow.objects.get(id=workflow_id)
        assert (workflow.version, OLD in json.dumps(workflow.actions), NEW in json.dumps(workflow.actions)) == (
            3,
            True,
            False,
        )
