from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import Integration

from products.slack_app.backend.services.message_footer import RunProvenance, app_home_url, reply_footer_block

TASK_URL = "https://us.posthog.com/project/1/tasks/2?runId=3"
DESKTOP_URL = "posthog-code://task/2"


class TestMessageFooter(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "everything",
                RunProvenance(TASK_URL, DESKTOP_URL, "claude-opus-5", "high"),
                "https://slack.com/app_redirect?app=A1&team=T1&tab=home",
                f"<{TASK_URL}|View on web> · <{DESKTOP_URL}|View on desktop>"
                " · *Claude Opus 5* · Reasoning: *High* · <https://slack.com/app_redirect?app=A1&team=T1&tab=home|Configure>",
            ),
            (
                "links_only",
                RunProvenance(TASK_URL, DESKTOP_URL),
                None,
                f"<{TASK_URL}|View on web> · <{DESKTOP_URL}|View on desktop>",
            ),
            ("model_without_effort", RunProvenance(model="claude-opus-5"), None, "*Claude Opus 5*"),
            (
                "configure_only",
                RunProvenance(),
                "https://slack.com/app_redirect?app=A1&team=T1&tab=home",
                "<https://slack.com/app_redirect?app=A1&team=T1&tab=home|Configure>",
            ),
        ]
    )
    def test_renders_present_segments_as_slack_links(
        self, _name: str, provenance: RunProvenance, configure_url: str | None, expected: str
    ) -> None:
        # Slack's mrkdwn linkifies `<url|label>` only. CommonMark `[label](url)` renders as
        # literal text, so the segment syntax is load-bearing, not cosmetic.
        block = reply_footer_block(provenance, configure_url)

        assert block == {"type": "context", "elements": [{"type": "mrkdwn", "text": expected}]}

    def test_contributes_no_block_when_there_is_nothing_to_say(self) -> None:
        # A context block with an empty `elements` list is rejected by Slack, which would
        # fail the whole message post rather than just dropping the footer.
        assert reply_footer_block(RunProvenance()) is None

    @parameterized.expand(
        [
            ("resolves", {"app_id": "A1"}, "T1", "https://slack.com/app_redirect?app=A1&team=T1&tab=home"),
            ("no_app_id", {}, "T1", None),
            ("no_workspace", {"app_id": "A1"}, "", None),
        ]
    )
    def test_app_home_url_needs_both_ids(
        self, _name: str, config: dict, integration_id: str, expected: str | None
    ) -> None:
        # Installs predating the OAuth path may carry no `app_id`; interpolating it anyway
        # would put an `app=None` link under every reply.
        integration = Integration(config=config, integration_id=integration_id)

        assert app_home_url(integration) == expected
