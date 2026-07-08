from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.mentions import extract_mention_emails


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
