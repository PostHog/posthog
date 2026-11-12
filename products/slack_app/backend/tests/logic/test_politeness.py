from django.test import SimpleTestCase

from parameterized import parameterized

from products.slack_app.backend.logic.politeness import is_polite_request


class TestIsPoliteRequest(SimpleTestCase):
    @parameterized.expand(
        [
            ("please", "<@UBOT> please fix the login redirect", True),
            ("please in any case", "PLEASE look at the funnel", True),
            ("thank you", "check signups for last week, thank you!", True),
            ("thank you across a line break", "check signups thank\nyou", True),
            ("no polite phrase", "check signups for last week", False),
            ("please inside another word", "the app pleases nobody", False),
            ("thanks is not thank you", "check signups, thanks", False),
            ("empty text", "", False),
            ("no text", None, False),
        ]
    )
    def test_polite_phrases(self, _name, text, expected):
        assert is_polite_request(text) is expected
