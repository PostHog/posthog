import unittest

from parameterized import parameterized

from products.tasks.backend.temporal.slack_relay.activities import _markdown_to_slack_mrkdwn
from products.tasks.backend.temporal.slack_relay.object_tags import (
    rewrite_object_tags_for_slack,
    split_incomplete_tag_suffix,
)

PROJECT = "https://us.posthog.com/project/2"
UUID = "0190f8a1-7c3e-7b2a-9d4f-2a1b3c4d5e6f"


def rewrite(text: str) -> str:
    return rewrite_object_tags_for_slack(text, project_url=PROJECT)


class TestRewriteObjectTagsForSlack(unittest.TestCase):
    @parameterized.expand(
        [
            ("insight", "9pQx3", "/insights/9pQx3"),
            ("dashboard", "123", "/dashboard/123"),
            ("error", UUID, f"/error_tracking/{UUID}"),
            ("replay", "0190f8a1-sess", "/replay/0190f8a1-sess"),
            ("flag", "42", "/feature_flags/42"),
            ("experiment", "7", "/experiments/7"),
            ("survey", UUID, f"/surveys/{UUID}"),
            ("ticket", UUID, f"/support/tickets/{UUID}"),
            ("trace", UUID, f"/ai-observability/traces/{UUID}"),
            ("eval", "5", "/ai-evals/evaluations/5"),
            ("event", UUID, f"/data-management/events/{UUID}"),
            ("cohort", "9", "/cohorts/9"),
            ("action", "11", "/data-management/actions/11"),
            ("person", UUID, f"/persons/{UUID}"),
            ("person", "a b", "/persons/a%20b"),
            ("session-replay", "sess", "/replay/sess"),
            ("session_replay", "sess", "/replay/sess"),
            ("recording", "sess", "/replay/sess"),
            ("feature-flag", "42", "/feature_flags/42"),
            ("feature_flag", "42", "/feature_flags/42"),
            ("sql", "SELECT 1", "/sql?open_query=SELECT%201"),
        ]
    )
    def test_every_kind_and_alias_links_to_its_page(self, tag: str, object_id: str, path: str) -> None:
        if tag == "sql":
            text = f'<sql label="label">{object_id}</sql>'
        else:
            text = f'<{tag} id="{object_id}">label</{tag}>'
        separator = "&" if "?" in path else "?"
        assert rewrite(text) == f"[label]({PROJECT}{path}{separator}unfurl=false)"

    @parameterized.expand(
        [
            ("flag_cited_by_key", '<flag id="new-checkout-flow">new-checkout-flow</flag>', "new-checkout-flow"),
            ("event_cited_by_name", '<event id="$pageview">pageview</event>', "pageview"),
            ("unknown_kind_with_id", '<inbox id="019f">Split generated PRs</inbox>', "Split generated PRs"),
        ]
    )
    def test_reference_without_a_page_keeps_only_its_label(self, _name: str, text: str, expected: str) -> None:
        assert rewrite(f"before {text} after") == f"before {expected} after"

    @parameterized.expand(
        [
            (
                "self_closing_inline_uses_kind_and_id_as_label",
                'Rolled out <flag id="42"/> yesterday.',
                f"Rolled out [Feature flag 42]({PROJECT}/feature_flags/42?unfurl=false) yesterday.",
            ),
            (
                "block_insight_keeps_unfurl_on",
                '<insight id="THgiHKou" display="block"/>',
                f"[Insight THgiHKou]({PROJECT}/insights/THgiHKou)",
            ),
            (
                "block_replay_links_into_player",
                '<replay id="sess-1" display="block"/>',
                f"[Session replay sess-1]({PROJECT}/replay/sess-1)",
            ),
            (
                "title_attribute_wins_over_body_and_id",
                '<insight id="abc" title="Checkout funnel" display="block"/>',
                f"[Checkout funnel]({PROJECT}/insights/abc)",
            ),
            (
                "escaped_sql_body_is_unescaped_before_linking",
                '<hogql label="small">SELECT value &lt; 3</hogql>',
                f"[small]({PROJECT}/sql?open_query=SELECT%20value%20%3C%203&unfurl=false)",
            ),
            (
                "html_entities_that_are_not_xml_stay_in_the_sql",
                "<hogql label=\"mark\">SELECT '&copy;'</hogql>",
                f"[mark]({PROJECT}/sql?open_query=SELECT%20%27%26copy%3B%27&unfurl=false)",
            ),
            (
                "inline_tag_right_after_a_block_starts_its_own_paragraph",
                '<hogql display="block" title="T">SELECT 1</hogql><insight id="1">x</insight>',
                f"**[T]({PROJECT}/sql?open_query=SELECT%201&unfurl=false)**\n```\nSELECT 1\n```\n\n[x]({PROJECT}/insights/1?unfurl=false)",
            ),
            (
                "backtick_identifiers_in_sql_do_not_hide_the_tag",
                '<hogql display="block" title="Events">SELECT `event` FROM events</hogql>',
                f"**[Events]({PROJECT}/sql?open_query=SELECT%20%60event%60%20FROM%20events&unfurl=false)**\n```\nSELECT `event` FROM events\n```",
            ),
            (
                "legacy_id_in_body_form_links_to_the_insight",
                "See <insight>abc123</insight> for the trend.",
                f"See [Insight abc123]({PROJECT}/insights/abc123?unfurl=false) for the trend.",
            ),
            (
                "title_only_query_tag_keeps_the_title",
                '<insight title="Signups by day" query_kind="TrendsQuery">{"kind":"TrendsQuery"}</insight>',
                "Signups by day",
            ),
            (
                "inline_hogql_links_to_sql_editor",
                'See <hogql label="signups today">SELECT count() FROM events</hogql>.',
                f"See [signups today]({PROJECT}/sql?open_query=SELECT%20count%28%29%20FROM%20events&unfurl=false).",
            ),
            (
                "label_characters_that_break_slack_links_are_dropped",
                '<insight id="1">a | b [d]</insight>',
                f"[a b d]({PROJECT}/insights/1?unfurl=false)",
            ),
            (
                "comparison_operators_in_labels_become_entities",
                '<insight id="1" title="Error rate &gt; 1%"/> and <insight id="2">users < 30 days</insight>',
                f"[Error rate &gt; 1%]({PROJECT}/insights/1?unfurl=false) and [users &lt; 30 days]({PROJECT}/insights/2?unfurl=false)",
            ),
            (
                "xml_entities_in_attributes_are_unescaped",
                '<hogql label="a &amp; b">SELECT 1</hogql>',
                f"[a & b]({PROJECT}/sql?open_query=SELECT%201&unfurl=false)",
            ),
        ]
    )
    def test_rewrites(self, _name: str, text: str, expected: str) -> None:
        assert rewrite(text) == expected

    @parameterized.expand(
        [
            ("unknown_self_closing_tag", "line one<br/>line two"),
            ("unterminated_tag", 'The <insight id="9pQx3">checkout funnel dropped.'),
            ("tag_missing_id", "<insight>checkout funnel</insight>"),
            ("tag_inside_inline_code", 'Write `<insight id="1">x</insight>` to cite.'),
            ("tag_inside_double_backtick_code", 'Write ``<insight id="1">x</insight>`` to cite.'),
            ("tag_inside_fenced_code", '```xml\n<insight id="1">x</insight>\n```'),
            ("tag_inside_unclosed_fence", 'Example:\n```xml\n<insight id="1">x</insight>'),
            ("tag_inside_tilde_fence", '~~~\n<insight id="1">x</insight>\n~~~'),
            ("text_without_tags", "plain **bold** text"),
        ]
    )
    def test_leaves_text_alone(self, _name: str, text: str) -> None:
        assert rewrite(text) == text

    def test_block_hogql_becomes_titled_fenced_sql_in_its_own_paragraph(self) -> None:
        text = (
            "Here is the split:\n"
            '<hogql display="block" title="Unassigned %" caption="Ready-only strips the mix shift">'
            "SELECT day,\n       count() AS n\nFROM reports\nGROUP BY day</hogql>\n"
            "Aug 26 is still partial."
        )
        assert rewrite(text) == (
            "Here is the split:\n\n"
            f"**[Unassigned %]({PROJECT}/sql?open_query=SELECT%20day%2C%0A%20%20%20%20%20%20%20count%28%29%20AS%20n%0AFROM%20reports%0AGROUP%20BY%20day&unfurl=false)**\n"
            "```\n"
            "SELECT day,\n       count() AS n\nFROM reports\nGROUP BY day\n"
            "```\n"
            "_Ready-only strips the mix shift_\n\n"
            "Aug 26 is still partial."
        )

    def test_block_hogql_with_oversized_sql_keeps_the_sql_but_drops_the_link(self) -> None:
        sql = "SELECT " + ", ".join(f"col_{i}" for i in range(400))
        rendered = rewrite(f'<hogql display="block" title="Wide">{sql}</hogql>')
        assert rendered == f"**Wide**\n```\n{sql}\n```"

    def test_many_tags_in_one_message_all_rewrite(self) -> None:
        text = " ".join(f'<insight id="i{i}">insight {i}</insight>' for i in range(500))
        rendered = rewrite(text)
        assert "<insight" not in rendered
        assert rendered.count("](") == 500

    def test_code_spans_interleaved_with_tags_only_skip_the_code(self) -> None:
        text = " ".join('`<flag id="1"/>` <flag id="2">live</flag>' for _ in range(200))
        rendered = rewrite(text)
        assert rendered.count('`<flag id="1"/>`') == 200
        assert rendered.count(f"[live]({PROJECT}/feature_flags/2?unfurl=false)") == 200

    def test_long_backtick_runs_do_not_hide_tags_or_stall(self) -> None:
        # Runs of different lengths never pair into a code span, so the tag between them is live.
        text = "x " + "`" * 20000 + ' <flag id="42">beta</flag> ' + "`" * 19999
        assert rewrite(text).count(f"[beta]({PROJECT}/feature_flags/42?unfurl=false)") == 1

    def test_unmatched_openers_do_not_stop_later_tags_rewriting(self) -> None:
        text = ('<insight id="open"> ' * 300) + '<flag id="42">beta</flag>'
        rendered = rewrite(text)
        assert rendered.endswith(f"[beta]({PROJECT}/feature_flags/42?unfurl=false)")
        assert rendered.count('<insight id="open">') == 300

    def test_rewritten_output_survives_mrkdwn_conversion(self) -> None:
        text = (
            'Two tiles: <insight id="F6tNdPRe">ready-only</insight> and <insight id="jjF0PSO2" display="block"/>\n\n'
            '<hogql display="block" title="DAU">SELECT 1</hogql>'
        )
        converted = _markdown_to_slack_mrkdwn(rewrite(text))
        assert f"<{PROJECT}/insights/F6tNdPRe?unfurl=false|ready-only>" in converted
        assert f"<{PROJECT}/insights/jjF0PSO2|Insight jjF0PSO2>" in converted
        assert f"*<{PROJECT}/sql?open_query=SELECT%201&unfurl=false|DAU>*" in converted
        assert "```\nSELECT 1\n```" in converted
        assert "<hogql" not in converted

    def test_entities_in_labels_survive_mrkdwn_conversion(self) -> None:
        converted = _markdown_to_slack_mrkdwn(rewrite('<insight id="1" title="Error rate > 1%"/>'))
        assert converted == f"<{PROJECT}/insights/1?unfurl=false|Error rate &gt; 1%>"


class TestSplitIncompleteTagSuffix(unittest.TestCase):
    @parameterized.expand(
        [
            ("opener_cut_mid_attribute", 'The <insight id="9pQ', "The ", '<insight id="9pQ'),
            ("opener_cut_before_name", "The <", "The ", "<"),
            ("body_still_streaming", 'The <insight id="1">check', "The ", '<insight id="1">check'),
            (
                "complete_tag_is_sent",
                'The <insight id="1">x</insight> dropped',
                'The <insight id="1">x</insight> dropped',
                "",
            ),
            ("self_closing_tag_is_sent", 'See <flag id="1"/> now', 'See <flag id="1"/> now', ""),
            ("comparison_is_not_a_tag", "a < b and c", "a < b and c", ""),
            ("unknown_tag_is_sent", "x <unknown>y", "x <unknown>y", ""),
            ("whole_text_is_held_when_it_is_all_one_open_tag", '<insight id="1">check', "", '<insight id="1">check'),
            (
                "open_fence_is_held",
                'Example:\n```xml\n<insight id="1">x</insight>',
                "Example:\n",
                '```xml\n<insight id="1">x</insight>',
            ),
            ("closed_fence_is_sent", "```\nx\n```\ndone", "```\nx\n```\ndone", ""),
        ]
    )
    def test_split(self, _name: str, text: str, sendable: str, held: str) -> None:
        split = split_incomplete_tag_suffix(text)
        assert (split.sendable, split.held) == (sendable, held)

    def test_oversized_suffix_is_sent_rather_than_held(self) -> None:
        text = "intro " + '<insight id="1">' + "x" * 5000
        split = split_incomplete_tag_suffix(text)
        assert split.held == ""
        assert split.sendable == text
