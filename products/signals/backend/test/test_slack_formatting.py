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
            ("reference_carrying_a_link_title", '[Daily](chart:daily "Daily signups")', "Daily"),
            # A title may contain parens. Ending the match at the first one leaves `")` in the prose.
            ("title_containing_parens", '[Daily](chart:daily "Daily signups (UTC)")', "Daily"),
            ("single_quoted_title", "[Daily](chart:daily 'Daily signups')", "Daily"),
            # CommonMark's third title delimiter. mdast reads the destination as `chart:daily` and the
            # title as `UTC`, so the inbox draws the chart and Slack must not keep the raw syntax.
            ("parenthesized_title", "[Daily](chart:daily (UTC))", "Daily"),
            # CommonMark's angle-bracket destination. mdast unwraps it to the same `chart:daily`, so
            # the inbox draws the chart and Slack must not keep the raw syntax.
            ("angle_bracket_destination", "[Daily](<chart:daily>)", "Daily"),
            # CommonMark allows balanced brackets in a label, and an escaped one either way, so both
            # of these resolve in the inbox and both have to reduce to the label here.
            ("label_holding_balanced_brackets", "[Daily [EU]](chart:daily)", "Daily [EU]"),
            ("label_holding_escaped_brackets", r"[Daily \[EU\]](chart:daily)", r"Daily \[EU\]"),
            ("angle_bracket_destination_with_a_title", '[Daily](<chart:daily> "Daily signups")', "Daily"),
            # Neither is a reference the inbox resolves, so Slack should read what the author wrote.
            ("image_is_left_alone", "![Daily](chart:daily)", "![Daily](chart:daily)"),
            ("escaped_bracket_is_left_alone", r"\[Daily](chart:daily)", r"\[Daily](chart:daily)"),
            ("http_link_is_left_alone", "[Docs](https://posthog.com)", "[Docs](https://posthog.com)"),
            ("prose_without_a_reference", "Signups fell 60%.", "Signups fell 60%."),
            # The inbox resolves the reference form through its definition and draws the chart, so
            # Slack has to reduce both halves — the reference to its label, and the definition line,
            # which would otherwise show the raw `chart:` target.
            ("full_reference", "[Daily][daily]\n\n[daily]: chart:signups-drop", "Daily\n\n"),
            ("collapsed_reference", "[daily][]\n\n[daily]: chart:signups-drop", "daily\n\n"),
            ("shortcut_reference", "[daily]\n\n[daily]: chart:signups-drop", "daily\n\n"),
            # Matching is case-insensitive and collapses whitespace, the way CommonMark compares labels.
            ("reference_label_normalized", "[Daily  EU][DAILY EU]\n\n[daily eu]: chart:d", "Daily  EU\n\n"),
            # A definition pointing somewhere else isn't a chart, so the author's markup stands.
            (
                "non_chart_definition_is_left_alone",
                "[Daily][daily]\n\n[daily]: https://posthog.com",
                "[Daily][daily]\n\n[daily]: https://posthog.com",
            ),
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

    @parameterized.expand(
        [
            ("bare_open_brackets", "[" * 20_000),
            ("unclosed_references", "[a](chart:" * 2_000),
            ("unterminated_titles", '[a](chart:x "' * 2_000),
            ("unterminated_angle_destinations", "[a](<chart:x" * 2_000),
            # The nested-pair branch is the one that can make a start position consume before it
            # fails, so drive it with labels that never reach a destination.
            ("nested_labels_that_never_close", "[a[b]" * 4_000),
        ]
    )
    def test_a_summary_that_never_closes_a_reference_stays_cheap(self, _name: str, summary: str) -> None:
        # A character class that admits `[` makes every start position rescan the remaining suffix, so
        # a summary built from either half of the pattern costs seconds per Slack delivery. Bound both
        # well under the quadratic cost while staying loose enough not to flake on a slow runner.
        started = time.perf_counter()
        strip_chart_references(summary)

        assert time.perf_counter() - started < 0.5
