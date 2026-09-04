import time

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.slack_formatting import (
    SLACK_SECTION_TEXT_MAX_LEN,
    chunk_slack_mrkdwn,
    group_segments_to_limit,
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

    @parameterized.expand(
        [
            ("backtick_fence_heading", "```", "# not a heading"),
            ("tilde_fence_heading", "~~~", "# not a heading"),
            ("backtick_fence_bold_label", "```", "**not a label**"),
            ("tilde_fence_bold_label", "~~~", "**not a label**"),
        ]
    )
    def test_seam_inside_a_fence_does_not_split(self, _name: str, fence: str, inner: str) -> None:
        # The bug this guards: a `# ` line inside a fenced code block used to be read as a heading and
        # split there, orphaning the fence and mangling the snippet when each segment was converted.
        # A bold line in a config or JSON snippet is the same trap for the bold-label seam.
        summary = f"Intro.\n\n{fence}\n{inner}\nconfig value\n{fence}\n\nTail."
        assert split_markdown_by_headings(summary) == [summary]

    def test_a_fence_closes_only_on_a_marker_line_with_nothing_after_it(self) -> None:
        # CommonMark allows only trailing whitespace after a closing fence, so a marker line that
        # carries other text is still code. Reading it as the close resumes seam detection inside
        # the snippet and splits the report mid-fence, which mangles the code once each segment is
        # converted on its own.
        summary = "Intro.\n\n```\n```not-a-close\n\n**Evidence**\n\nstill code\n```\n\nTail."
        assert split_markdown_by_headings(summary) == [summary]

    def test_real_heading_after_a_fence_still_splits(self) -> None:
        summary = "```\n# in code\n```\n\n## Real heading\nbody"
        segments = split_markdown_by_headings(summary)

        assert segments[0].strip() == "```\n# in code\n```"
        assert segments[1].startswith("## Real heading")
        assert len(segments) == 2

    @parameterized.expand(
        [
            ("standalone_asterisks", "**Evidence**", "**Impact**"),
            ("standalone_underscores", "__Evidence__", "__Impact__"),
            ("colon_inside_the_bold_run", "**Evidence:**", "**Impact:**"),
            ("colon_after_the_bold_run", "**Evidence**:", "**Impact**:"),
            ("lead_paragraph_colon", "**Evidence**: two retries failed.", "**Impact**: one team."),
            ("lead_paragraph_hyphen", "**Evidence** - two retries failed.", "**Impact** - one team."),
            ("lead_paragraph_en_dash", "**Evidence** – two retries failed.", "**Impact** – one team."),
            ("lead_paragraph_inside_colon", "**Evidence:** two retries failed.", "**Impact:** one team."),
        ]
    )
    def test_bold_section_labels_split_like_headings(self, _name: str, first: str, second: str) -> None:
        # The bug this guards: scouts label their sections in bold far more often than they write an
        # ATX heading, and Slack renders both the same way. While only `#` counted as a seam, a
        # threaded delivery of such a report posted the whole summary as one message with no replies.
        summary = f"Lead line.\n\n{first}\n\nbody one\n\n{second}\n\nbody two"
        segments = split_markdown_by_headings(summary)

        assert segments[0].strip() == "Lead line."
        assert segments[1].startswith(first)
        assert segments[2].startswith(second)
        assert len(segments) == 3

    @parameterized.expand(
        [
            ("bold_number_opening_a_paragraph", "**31** organizations reported this.\n\n**42** did too."),
            ("bold_inside_a_paragraph", "Some text **bold** more text.\n\nAnother **bold** run here."),
            ("bold_line_with_no_blank_line_before_it", "Prose line.\n**Evidence**\nmore prose.\n\ntail"),
            ("bold_leading_a_list_item", "Lead.\n\n- **Evidence**: two retries\n- **Impact**: one team"),
            ("sentence_bolded_for_emphasis", "Lead.\n\n**" + "word " * 19 + "word**\n\n**" + "more " * 19 + "more**"),
        ]
    )
    def test_bold_that_is_not_a_section_label_is_no_seam(self, _name: str, summary: str) -> None:
        # Splitting on any bold run would cut a report mid-argument: a bolded number opening a
        # paragraph, an emphasized phrase, and a bold list label all read as section headings in
        # Slack but structure nothing. A seam needs a label shape and a block boundary before it.
        assert split_markdown_by_headings(summary) == [summary]

    @parameterized.expand(
        [
            (
                "repeated_headings_outrank_bold_labels",
                "Lead.\n\n## First\n\n**Evidence**\n\none\n\n## Second\n\n**Evidence**\n\ntwo",
                ["## First", "## Second"],
            ),
            (
                "a_lone_title_leaves_bold_labels_as_the_seam",
                "# Title\n\nLead.\n\n**Evidence**\n\none\n\n**Impact**\n\ntwo",
                ["**Evidence**", "**Impact**"],
            ),
            (
                "standalone_labels_outrank_bold_lead_paragraphs",
                "Lead.\n\n**First**\n\n**Detail** - one\n\n**Second**\n\n**Detail** - two",
                ["**First**", "**Second**"],
            ),
        ]
    )
    def test_the_summary_splits_at_its_shallowest_repeated_seam(
        self, _name: str, summary: str, expected_starts: list[str]
    ) -> None:
        # Seam detection must not assume one writing style. Real headings stay the primary seam, and
        # a bold label becomes the seam only when it is the shallowest structure the summary repeats
        # at, so a mixed report threads at its headings rather than bursting into a reply per label.
        segments = split_markdown_by_headings(summary)

        assert len(segments) == len(expected_starts) + 1
        assert [segment[: len(start)] for segment, start in zip(segments[1:], expected_starts)] == expected_starts


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


class TestGroupSegmentsToLimit(SimpleTestCase):
    @parameterized.expand([("at_the_limit", 3), ("one_over_the_limit", 4), ("far_over_the_limit", 40)])
    def test_the_lead_and_every_section_survive_grouping(self, _name: str, section_count: int) -> None:
        # A threaded delivery posts one Slack message per segment in sequence, so a summary that
        # labels every paragraph would post a reply each and flood the channel. Grouping has to
        # bound the count without dropping a section or folding one into the channel message.
        segments = ["lead\n\n"] + [f"**Label {index}**\n\nbody {index}\n\n" for index in range(section_count)]

        grouped = group_segments_to_limit(segments, limit=4)

        assert len(grouped) <= 4
        assert grouped[0] == "lead\n\n"
        assert "".join(grouped) == "".join(segments)
