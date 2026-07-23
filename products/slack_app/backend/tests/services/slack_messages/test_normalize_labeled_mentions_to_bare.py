import unittest

from parameterized import parameterized

from products.slack_app.backend.services.slack_messages import normalize_labeled_mentions_to_bare


class TestNormalizeLabeledMentionsToBare(unittest.TestCase):
    @parameterized.expand(
        [
            ("single_word_name", "hi <@U123|vojta>", "hi <@U123>"),
            ("name_with_space", "hi <@U123|Radu Raicea>", "hi <@U123>"),
            ("multiple_mentions", "<@U1|A B> and <@U2|C>", "<@U1> and <@U2>"),
            ("already_bare_untouched", "hi <@U123>", "hi <@U123>"),
            ("channel_link_kept", "see <#C123|general>", "see <#C123|general>"),
            ("url_link_kept", "<https://x.com|label>", "<https://x.com|label>"),
            ("broadcast_kept", "<!here>", "<!here>"),
        ]
    )
    def test_normalize(self, _name, text, expected):
        assert normalize_labeled_mentions_to_bare(text) == expected
