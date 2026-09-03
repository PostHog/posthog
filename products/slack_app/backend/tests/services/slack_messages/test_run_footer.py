from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import Integration

from products.slack_app.backend.services.slack_messages import (
    RunFooter,
    load_run_footer,
    reply_footer_block,
    viewer_has_code_access,
)

TASK_URL = "https://us.posthog.com/project/1/tasks/2?runId=3&unfurl=false"
DESKTOP_URL = "https://us.posthog.com/code/task/2?unfurl=false"


class TestRunFooter(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "everything",
                RunFooter(TASK_URL, DESKTOP_URL, "claude-opus-5", "high"),
                "slack://app?team=T1&id=A1&tab=home",
                f"<{TASK_URL}|View on web> · <{DESKTOP_URL}|View on desktop>"
                " · *Claude Opus 5* · Reasoning: *High* · <slack://app?team=T1&id=A1&tab=home|Configure>",
            ),
            (
                "links_only",
                RunFooter(TASK_URL, DESKTOP_URL),
                None,
                f"<{TASK_URL}|View on web> · <{DESKTOP_URL}|View on desktop>",
            ),
            ("model_without_effort", RunFooter(model="claude-opus-5"), None, "*Claude Opus 5*"),
            (
                "configure_only",
                RunFooter(),
                "slack://app?team=T1&id=A1&tab=home",
                "<slack://app?team=T1&id=A1&tab=home|Configure>",
            ),
        ]
    )
    def test_renders_present_segments_as_slack_links(
        self, _name: str, footer: RunFooter, configure_url: str | None, expected: str
    ) -> None:
        # Slack's mrkdwn linkifies `<url|label>` only. CommonMark `[label](url)` renders as
        # literal text, so the segment syntax is load-bearing, not cosmetic.
        block = reply_footer_block(footer, configure_url)

        assert block == {"type": "context", "elements": [{"type": "mrkdwn", "text": expected}]}

    def test_contributes_no_block_when_there_is_nothing_to_say(self) -> None:
        # A context block with an empty `elements` list is rejected by Slack, which would
        # fail the whole message post rather than just dropping the footer.
        assert reply_footer_block(RunFooter()) is None


class TestLoadRunFooter(SimpleTestCase):
    @patch("products.tasks.backend.facade.run_config.parse_run_state")
    @patch("products.tasks.backend.facade.api.get_task_run")
    def test_describes_the_run_links_included(self, mock_get_run, mock_parse) -> None:
        # Whether the reader may open the links is asked later, where the reader is known.
        task_id = uuid4()
        mock_get_run.return_value = SimpleNamespace(id=uuid4(), task_id=task_id, team_id=1, state={})
        mock_parse.return_value = SimpleNamespace(model="claude-opus-5", reasoning_effort="high")

        footer = load_run_footer("run-1")

        assert f"/code/task/{task_id}" in (footer.desktop_url or "")
        assert f"/tasks/{task_id}" in (footer.task_url or "")
        assert footer.model == "claude-opus-5"

    @patch("products.tasks.backend.facade.api.get_task_run", side_effect=RuntimeError("db down"))
    def test_a_failure_to_describe_the_run_costs_the_footer_not_the_answer(self, _mock_get_run) -> None:
        assert load_run_footer("run-1") == RunFooter()


class TestViewerHasCodeAccess(SimpleTestCase):
    def _integration(self) -> Integration:
        organization = SimpleNamespace(id="org-1")
        team = SimpleNamespace(organization=organization, organization_id=organization.id)
        return cast(Integration, SimpleNamespace(config={}, integration_id="T1", id=1, team=team))

    @patch("products.tasks.backend.facade.access.get_desktop_access_decision")
    def test_no_slack_identity_means_no_access_without_consulting_the_flag(self, mock_has_access) -> None:
        assert viewer_has_code_access(self._integration(), None) is False
        mock_has_access.assert_not_called()

    @patch("products.slack_app.backend.services.slack_user_oauth.find_linked_posthog_user", return_value=None)
    @patch("products.tasks.backend.facade.access.get_desktop_access_decision")
    def test_an_unlinked_slack_identity_means_no_access(self, mock_has_access, _mock_find) -> None:
        assert viewer_has_code_access(self._integration(), "U1") is False
        mock_has_access.assert_not_called()

    @parameterized.expand([("granted", True, True), ("denied", False, False)])
    @patch("products.slack_app.backend.services.slack_user_oauth.find_linked_posthog_user")
    @patch("products.tasks.backend.facade.access.get_desktop_access_decision")
    def test_a_linked_identity_follows_its_own_code_access(
        self, _name: str, granted: bool, expected: bool, mock_has_access, mock_find
    ) -> None:
        # The reader, not the task creator: a thread outlives whoever opened it.
        mock_find.return_value = object()
        mock_has_access.return_value = SimpleNamespace(allowed=granted)

        integration = self._integration()

        assert viewer_has_code_access(integration, "U1") is expected
        mock_find.assert_called_once_with(
            slack_user_id="U1",
            slack_team_id="T1",
            candidate_org_ids={integration.team.organization_id},
        )

    @patch(
        "products.slack_app.backend.services.slack_user_oauth.find_linked_posthog_user",
        side_effect=RuntimeError("db down"),
    )
    def test_a_lookup_failure_withholds_the_links_rather_than_guessing(self, _mock_find) -> None:
        assert viewer_has_code_access(self._integration(), "U1") is False
