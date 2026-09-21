from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.workflows.backend.management.commands import strip_placeholder_sender_overrides as command_module
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _email_action(action_id: str, from_value: dict) -> dict:
    return {
        "id": action_id,
        "type": "function_email",
        "config": {
            "template_id": "template-email",
            "inputs": {"email": {"value": {"from": from_value, "to": "a@b.com", "subject": "hi", "text": "hi"}}},
        },
    }


@patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
class TestStripPlaceholderSenderOverrides(BaseTest):
    def test_dry_run_changes_nothing(self, _mock_model_reload):
        flow = HogFlow.objects.create(
            team=self.team,
            name="legacy",
            actions=[_email_action("a1", {"integrationId": 1, "email": "default@example.com"})],
        )

        call_command("strip_placeholder_sender_overrides")

        flow.refresh_from_db()
        assert flow.actions[0]["config"]["inputs"]["email"]["value"]["from"]["email"] == "default@example.com"

    @patch(
        "products.workflows.backend.management.commands.strip_placeholder_sender_overrides.reload_hog_flows_on_workers"
    )
    def test_live_run(self, mock_command_reload, _mock_model_reload):
        # The old sender picker wrote email: 'default@example.com' into from on every sender pick.
        # The live-run must remove exactly that key, everywhere it sits (live actions and the draft
        # blob), keep every other from key, and never touch an address a customer actually typed.
        placeholder_from = {
            "integrationId": 1,
            "integrationIds": [1, 2],
            "name": "Support",
            "email": "default@example.com",
        }
        custom_from = {"integrationId": 1, "email": "team@customer.com"}
        affected = HogFlow.objects.create(
            team=self.team,
            name="legacy",
            actions=[
                _email_action("a1", dict(placeholder_from)),
                _email_action("a2", dict(custom_from)),
            ],
            draft={"actions": [_email_action("a1", dict(placeholder_from))]},
        )
        draft_only = HogFlow.objects.create(
            team=self.team,
            name="draft only",
            actions=[_email_action("a1", dict(custom_from))],
            draft={"actions": [_email_action("a1", dict(placeholder_from))]},
        )

        affected_updated_at_before = affected.updated_at
        draft_only_updated_at_before = draft_only.updated_at

        with self.captureOnCommitCallbacks(execute=True):
            call_command("strip_placeholder_sender_overrides", "--live-run")

        affected.refresh_from_db()
        cleaned_from = affected.actions[0]["config"]["inputs"]["email"]["value"]["from"]
        assert cleaned_from == {"integrationId": 1, "integrationIds": [1, 2], "name": "Support"}
        assert affected.actions[1]["config"]["inputs"]["email"]["value"]["from"] == custom_from
        affected_draft = affected.draft
        assert affected_draft is not None
        assert affected_draft["actions"][0]["config"]["inputs"]["email"]["value"]["from"] == {
            "integrationId": 1,
            "integrationIds": [1, 2],
            "name": "Support",
        }

        draft_only.refresh_from_db()
        assert draft_only.actions[0]["config"]["inputs"]["email"]["value"]["from"] == custom_from
        draft_only_draft = draft_only.draft
        assert draft_only_draft is not None
        assert "email" not in draft_only_draft["actions"][0]["config"]["inputs"]["email"]["value"]["from"]

        # The editor's stale-write fence compares against these timestamps. Without the bump, a
        # tab opened before the cleanup passes the fence and saves the placeholder straight back.
        assert affected.updated_at > affected_updated_at_before
        assert draft_only.updated_at == draft_only_updated_at_before
        assert draft_only.draft_updated_at is not None

        # Workers cache the live flow config, so a flow whose live actions changed must be
        # reloaded; a draft-only change runs nothing and must not be.
        mock_command_reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(affected.id)])

        # Idempotent: a second live-run finds nothing to strip.
        mock_command_reload.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("strip_placeholder_sender_overrides", "--live-run")
        mock_command_reload.assert_not_called()

    @patch(
        "products.workflows.backend.management.commands.strip_placeholder_sender_overrides.reload_hog_flows_on_workers"
    )
    def test_live_run_preserves_a_save_landing_between_scan_and_write(self, _mock_command_reload, _mock_model_reload):
        # The command must write the row it re-reads under lock, not the blob its scan saw.
        # Writing the scanned blob silently discards any workflow save that commits in between.
        flow = HogFlow.objects.create(
            team=self.team,
            name="legacy",
            actions=[_email_action("a1", {"integrationId": 1, "email": "default@example.com"})],
        )
        concurrent_actions = [
            _email_action("a1", {"integrationId": 1, "email": "default@example.com"}),
            _email_action("a2", {"integrationId": 2, "email": "team@customer.com"}),
        ]

        real_strip = command_module._strip_placeholder
        fired = False

        def strip_with_concurrent_save(actions):
            nonlocal fired
            if not fired:
                fired = True
                HogFlow.objects.filter(pk=flow.pk).update(actions=concurrent_actions)
            return real_strip(actions)

        with patch.object(command_module, "_strip_placeholder", side_effect=strip_with_concurrent_save):
            call_command("strip_placeholder_sender_overrides", "--live-run")

        flow.refresh_from_db()
        assert len(flow.actions) == 2, "the save that landed mid-command was discarded"
        assert "email" not in flow.actions[0]["config"]["inputs"]["email"]["value"]["from"]
        assert flow.actions[1]["config"]["inputs"]["email"]["value"]["from"]["email"] == "team@customer.com"
