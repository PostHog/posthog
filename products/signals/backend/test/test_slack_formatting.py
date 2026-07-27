import time

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.slack_formatting import markdown_to_slack_mrkdwn, strip_chart_references


class TestStripChartReferences(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "inline_reference",
                "Signups fell 60%. [Daily signups](chart:signups-drop)",
                "Signups fell 60%. Daily signups",
            ),
            ("several_in_one_summary", "[a](chart:x) then [b](chart:y_2-z)", "a then b"),
            ("target_outside_the_id_charset", "[Bad](chart:Uppercase)", "Bad"),
            ("http_link_is_left_alone", "[Docs](https://posthog.com)", "[Docs](https://posthog.com)"),
            ("prose_without_a_reference", "Signups fell 60%.", "Signups fell 60%."),
        ]
    )
    def test_reduces_chart_links_to_their_label(self, _name: str, summary: str, expected: str) -> None:
        assert strip_chart_references(summary) == expected

    def test_stripped_summary_survives_slack_conversion_without_markup(self) -> None:
        # Left in place, the converter emits `<chart:signups-drop|Daily signups>`, which the safety
        # wrapper escapes because the destination is not http(s) — visible markup in every
        # notification for a report carrying an inline chart.
        rendered = markdown_to_slack_mrkdwn(strip_chart_references("[Daily signups](chart:signups-drop)"))

        assert "chart:" not in rendered
        assert "&lt;" not in rendered
        assert "Daily signups" in rendered

    def test_a_summary_of_open_brackets_stays_cheap(self) -> None:
        # A label class that admits `[` makes every start position rescan the remaining suffix, so a
        # summary of nothing but `[` costs seconds per Slack delivery. Bound it well under the
        # quadratic cost while staying loose enough not to flake on a slow runner.
        started = time.perf_counter()
        strip_chart_references("[" * 20_000)

        assert time.perf_counter() - started < 0.5
