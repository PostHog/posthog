from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.mentions import extract_mention_emails, render_mention_tokens


class ExtractMentionEmailsTest(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_mention", "hey @[Ann](ann@example.com), thoughts?", {"ann@example.com"}),
            (
                "multiple_mentions",
                "@[Ann](ann@example.com) and @[Bob Two](bob@example.com)",
                {"ann@example.com", "bob@example.com"},
            ),
            ("lowercased_and_deduped", "@[Ann](Ann@Example.COM) again @[Ann](ann@example.com)", {"ann@example.com"}),
            ("plain_email_is_not_a_mention", "mail ann@example.com directly", set()),
            ("invalid_email_in_token", "@[Ann](not-an-email)", set()),
            ("whitespace_in_email", "@[Ann](ann @example.com)", set()),
            ("bracket_in_name_breaks_token", "@[An[n](ann@example.com)", set()),
            ("newline_in_name_breaks_token", "@[An\nn](ann@example.com)", set()),
            ("empty_content", "", set()),
        ]
    )
    def test_extract_mention_emails(self, _name, content, expected):
        assert extract_mention_emails(content) == expected


class RenderMentionTokensTest(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_mention", "hey @[Ann](ann@example.com), thoughts?", "hey @Ann, thoughts?"),
            (
                "multiple_mentions",
                "@[Ann](ann@example.com) and @[Bob Two](bob@example.com)",
                "@Ann and @Bob Two",
            ),
            ("non_token_text_untouched", "mail ann@example.com directly", "mail ann@example.com directly"),
            ("malformed_token_untouched", "@[Ann](not-an-email)", "@[Ann](not-an-email)"),
            ("empty_content", "", ""),
        ]
    )
    def test_render_mention_tokens(self, _name, content, expected):
        assert render_mention_tokens(content) == expected
