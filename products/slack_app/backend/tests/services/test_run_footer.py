from types import SimpleNamespace
from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.slack_app.backend.services.run_footer import RunFooter, load_run_footer, reply_footer_block

TASK_URL = "https://us.posthog.com/project/1/tasks/2?runId=3"
DESKTOP_URL = "posthog-code://task/2"


class TestRunFooter(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "everything",
                RunFooter(TASK_URL, DESKTOP_URL, "claude-opus-5", "high"),
                "https://slack.com/app_redirect?app=A1&team=T1&tab=home",
                f"<{TASK_URL}|View on web> · <{DESKTOP_URL}|View on desktop>"
                " · *Claude Opus 5* · Reasoning: *High* · <https://slack.com/app_redirect?app=A1&team=T1&tab=home|Configure>",
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
                "https://slack.com/app_redirect?app=A1&team=T1&tab=home",
                "<https://slack.com/app_redirect?app=A1&team=T1&tab=home|Configure>",
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
    def _run(self, created_by_id: int | None):
        return SimpleNamespace(
            id=uuid4(),
            task_id=uuid4(),
            team_id=1,
            state={"model": "claude-opus-5"},
            created_by_id=created_by_id,
        )

    @patch("products.slack_app.backend.services.run_footer.User")
    @patch("products.tasks.backend.facade.access.has_tasks_access")
    @patch("products.tasks.backend.facade.api.get_task_run")
    def test_a_run_with_no_creator_gets_no_links_without_consulting_the_flag(
        self, mock_get_run, mock_has_access, _mock_user
    ) -> None:
        # Links lead somewhere the reader may not be able to open, so a run we cannot
        # attribute must not carry them — and must not cost a flag call to find out.
        mock_get_run.return_value = self._run(created_by_id=None)

        footer = load_run_footer("run-1")

        mock_has_access.assert_not_called()
        assert (footer.task_url, footer.desktop_url) == (None, None)
        # The model is not access-sensitive, so it survives the gate.
        assert footer.model == "claude-opus-5"

    @patch("products.slack_app.backend.services.run_footer.User")
    @patch("products.tasks.backend.facade.access.has_tasks_access", side_effect=RuntimeError("flags down"))
    @patch("products.tasks.backend.facade.api.get_task_run")
    def test_a_flag_service_blip_withholds_the_links_rather_than_guessing(
        self, mock_get_run, _mock_has_access, _mock_user
    ) -> None:
        mock_get_run.return_value = self._run(created_by_id=7)

        footer = load_run_footer("run-1")

        assert (footer.task_url, footer.desktop_url) == (None, None)

    @patch("products.tasks.backend.facade.api.get_task_run", side_effect=RuntimeError("db down"))
    def test_a_failure_to_describe_the_run_costs_the_footer_not_the_answer(self, _mock_get_run) -> None:
        assert load_run_footer("run-1") == RunFooter()
