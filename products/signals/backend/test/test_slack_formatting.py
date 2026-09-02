import time

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.slack_formatting import (
    SLACK_SECTION_TEXT_MAX_LEN,
    chunk_slack_mrkdwn,
    markdown_to_slack_mrkdwn,
    split_markdown_by_headings,
    strip_chart_references,
)


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


class TestSplitMarkdownByHeadings(SimpleTestCase):
    def test_lead_precedes_one_segment_per_heading(self) -> None:
        summary = "Intro line.\n\n## First\nbody one\n\n## Second\nbody two"
        segments = split_markdown_by_headings(summary)

        assert segments[0].strip() == "Intro line."
        assert segments[1].startswith("## First")
        assert segments[2].startswith("## Second")
        assert len(segments) == 3

    def test_sub_headings_stay_inside_their_parent_segment(self) -> None:
        # A split at every level bursts a sub-headed report into a segment per sub-point, which the
        # reader gets as one Slack reply each. The split runs at the level the summary repeats at.
        summary = "## First\nbody one\n\n### Detail\nmore\n\n## Second\nbody two"
        segments = split_markdown_by_headings(summary)

        assert segments == ["", "## First\nbody one\n\n### Detail\nmore\n\n", "## Second\nbody two"]

    def test_a_lone_top_heading_is_not_a_split_point(self) -> None:
        # A level used once is the summary's own title. Splitting there returns everything under it
        # as a single segment, which is the wall of text threading exists to break up.
        summary = "# Title\n\nIntro line.\n\n## First\nbody one\n\n## Second\nbody two"
        segments = split_markdown_by_headings(summary)

        assert segments[0].strip() == "# Title\n\nIntro line."
        assert segments[1].startswith("## First")
        assert segments[2].startswith("## Second")
        assert len(segments) == 3

    def test_leading_heading_yields_empty_lead(self) -> None:
        segments = split_markdown_by_headings("## Only\nbody")

        assert segments[0] == ""
        assert segments[1].startswith("## Only")

    def test_summary_without_headings_stays_one_segment(self) -> None:
        assert split_markdown_by_headings("no headings here") == ["no headings here"]

    def test_empty_summary_yields_no_segments(self) -> None:
        assert split_markdown_by_headings("   ") == []

    @parameterized.expand([("backtick_fence", "```"), ("tilde_fence", "~~~")])
    def test_column_zero_hash_inside_a_fence_does_not_split(self, _name: str, fence: str) -> None:
        # The bug this guards: a `# ` line inside a fenced code block used to be read as a heading and
        # split there, orphaning the fence and mangling the snippet when each segment was converted.
        summary = f"Intro.\n\n{fence}\n# not a heading\nconfig value\n{fence}\n\nTail."
        assert split_markdown_by_headings(summary) == [summary]

    def test_real_heading_after_a_fence_still_splits(self) -> None:
        summary = "```\n# in code\n```\n\n## Real heading\nbody"
        segments = split_markdown_by_headings(summary)

        assert segments[0].strip() == "```\n# in code\n```"
        assert segments[1].startswith("## Real heading")
        assert len(segments) == 2


class TestChunkSlackMrkdwn(SimpleTestCase):
    def test_short_text_is_one_chunk(self) -> None:
        assert chunk_slack_mrkdwn("short") == ["short"]

    def test_long_text_splits_within_the_section_limit_without_losing_the_tail(self) -> None:
        # The bug this guards: a summary past the section cap used to be truncated with an ellipsis,
        # dropping everything after ~2,900 characters. Chunking must keep every line.
        lines = [f"line {index}" for index in range(600)]
        chunks = chunk_slack_mrkdwn("\n".join(lines))

        assert len(chunks) > 1
        assert all(len(chunk) <= SLACK_SECTION_TEXT_MAX_LEN for chunk in chunks)
        recovered = "\n".join(chunks)
        assert all(line in recovered for line in lines)

    @parameterized.expand(
        [
            ("plain_run", "x" * (SLACK_SECTION_TEXT_MAX_LEN * 2 + 5)),
            ("link_longer_than_a_section", "<https://example.com/" + "z" * (SLACK_SECTION_TEXT_MAX_LEN * 2) + "|l>"),
        ]
    )
    def test_unbreakable_run_is_hard_sliced(self, _name: str, line: str) -> None:
        # A run with no sentence, word, or token boundary has nowhere safe to break, so it is sliced
        # at the limit. Guards both halves of that fallback: it has to terminate, and it has to keep
        # every character rather than dropping the remainder.
        chunks = chunk_slack_mrkdwn(line)

        assert all(len(chunk) <= SLACK_SECTION_TEXT_MAX_LEN for chunk in chunks)
        assert "".join(chunks) == line

    @parameterized.expand(
        [
            ("sentence_ends", "The mount call times out and the retry never fires. "),
            ("no_sentence_ends", "mount timeout retry never fires again "),
        ]
    )
    def test_text_only_report_never_breaks_mid_word(self, _name: str, sentence: str) -> None:
        # The bug this guards: a report with no Markdown headings is one long line, which used to be
        # sliced at exactly the section cap, so a reply opened mid-word ("...since Tue" / "sday and
        # the retry..."). Comparing word sequences catches that, because a mid-word cut turns one
        # word into two and no longer round-trips.
        line = (sentence * 400).strip()
        chunks = chunk_slack_mrkdwn(line)

        assert len(chunks) > 1
        assert all(len(chunk) <= SLACK_SECTION_TEXT_MAX_LEN for chunk in chunks)
        assert " ".join(chunks).split() == line.split()

    def test_link_spanning_the_section_boundary_is_kept_whole(self) -> None:
        # The bug this guards: a cut inside a converter-emitted `<url|label>` token leaves half a
        # link in each message, and Slack renders both halves as visible junk.
        link = "<https://example.com/a/very/long/path|the failing request>"
        line = "x" * (SLACK_SECTION_TEXT_MAX_LEN - 20) + link + " and the prose that follows it."
        chunks = chunk_slack_mrkdwn(line)

        assert all(len(chunk) <= SLACK_SECTION_TEXT_MAX_LEN for chunk in chunks)
        assert any(link in chunk for chunk in chunks)
