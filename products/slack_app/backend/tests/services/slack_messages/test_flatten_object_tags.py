import unittest

from parameterized import parameterized

from products.slack_app.backend.services.slack_messages import flatten_object_tags


class TestFlattenObjectTags(unittest.TestCase):
    @parameterized.expand(
        [
            ("hogql_without_label", "<hogql>SELECT 1</hogql>", "SQL query"),
            ("sql_without_label", "<sql>SELECT 1</sql>", "SQL query"),
            (
                "inline_reference_keeps_label",
                'The <insight id="9pQx3">checkout funnel</insight> dropped',
                "The checkout funnel dropped",
            ),
            (
                "hogql_keeps_label_and_drops_sql",
                '<hogql label="signups today">SELECT count() FROM events</hogql> looks flat',
                "signups today looks flat",
            ),
            (
                "title_wins_over_body",
                '<flag id="42" title="new checkout">whatever</flag>',
                "new checkout",
            ),
            (
                "block_chart_keeps_its_title",
                '<hogql display="block" title="Daily active users">SELECT 1</hogql>',
                "Daily active users",
            ),
            (
                "self_closing_tag_with_no_label_drops_out",
                'Watch this: <replay id="abc123" display="block"/>',
                "Watch this: ",
            ),
            (
                "escaped_entities_in_label_are_decoded",
                '<cohort id="7" title="Signed up &amp; active">x</cohort>',
                "Signed up & active",
            ),
            (
                "alias_kind_is_flattened",
                '<feature-flag id="42">new-checkout</feature-flag>',
                "new-checkout",
            ),
            (
                "two_tags_of_one_kind_both_flatten",
                'The <insight id="1">funnel</insight> and the <insight id="2">retention curve</insight>',
                "The funnel and the retention curve",
            ),
            (
                "unknown_tag_stays_literal",
                "<summary>a recap</summary>",
                "<summary>a recap</summary>",
            ),
            (
                "tag_inside_inline_code_is_flattened",
                'Write `<insight id="9pQx3">label</insight>` to cite one',
                "Write `label` to cite one",
            ),
            (
                "tag_inside_fence_is_flattened",
                '```\n<hogql label="x">SELECT 1</hogql>\n```',
                "```\nx\n```",
            ),
            (
                "half_streamed_tag_is_left_alone",
                'Checking <insight id="9pQx3">che',
                'Checking <insight id="9pQx3">che',
            ),
            (
                "inbox_report_is_flattened",
                '<report id="report-1">Investigation</report>',
                "Investigation",
            ),
            (
                "tilde_fence",
                '~~~xml\n<insight id="1">Example</insight>\n~~~',
                "~~~xml\nExample\n~~~",
            ),
            ("open_fence", '```xml\n<insight id="1">Example</insight>', "```xml\nExample"),
            (
                "long_fence",
                '````xml\n```\n<insight id="1">Example</insight>\n````',
                "````xml\n```\nExample\n````",
            ),
            ("indented_code", '    <insight id="1">Example</insight>\n', "    Example\n"),
            ("tab_indented_code", '\t<insight id="1">Example</insight>\n', "\tExample\n"),
            (
                "quoted_fence",
                '> ```xml\n> <insight id="1">Example</insight>\n> ```',
                "> ```xml\n> Example\n> ```",
            ),
            (
                "double_backtick",
                'Use ``<insight id="1">Example</insight>``.',
                "Use ``Example``.",
            ),
            (
                "multiline_inline_code",
                'Use ``one\n<insight id="1">Example</insight>\ntwo``.',
                "Use ``one\nExample\ntwo``.",
            ),
            (
                "escaped_channel_mention",
                '<insight title="&lt;!channel&gt;">Example</insight>',
                "&lt;!channel&gt;",
            ),
            (
                "escaped_user_mention",
                '<hogql label="&lt;@U000EXAMPLE&gt;">SELECT 1</hogql>',
                "&lt;@U000EXAMPLE&gt;",
            ),
            (
                "literal_mention_in_title",
                '<insight title="<!channel>">Example</insight>',
                "&lt;!channel&gt;",
            ),
            ("literal_mention_in_body", '<insight id="1"><!here></insight>', "&lt;!here&gt;"),
            ("explicit_mention_outside_tag", "<!here>", "<!here>"),
            (
                "mixed_code_and_prose",
                'Read <insight id="1">One</insight>.\n\n~~~xml\n<insight id="1">Example</insight>\n~~~\n\nRead <insight id="2">Two</insight>.',
                "Read One.\n\n~~~xml\nExample\n~~~\n\nRead Two.",
            ),
            ("empty_text_unchanged", "", ""),
            ("plain_text_unchanged", "No tags here", "No tags here"),
        ]
    )
    def test_flatten(self, _name, text, expected):
        assert flatten_object_tags(text) == expected
