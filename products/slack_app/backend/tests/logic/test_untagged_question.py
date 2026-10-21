from django.test import SimpleTestCase

from parameterized import parameterized

from products.slack_app.backend.logic.untagged_question import is_untagged_question_candidate


class TestIsUntaggedQuestionCandidate(SimpleTestCase):
    @parameterized.expand(
        [
            ("a question mark", "signups by country last month?", True),
            ("a question word first", "how many people signed up last week", True),
            ("a request word first", "need signups by country for last month", True),
            ("a request phrase inside", "hey team, looking for the churn dashboard", True),
            ("a statement that names PostHog", "the PostHog funnel looks off since the deploy", True),
            ("a statement", "Shipped the new export filter today", False),
            ("PostHog only in a link", "shipped it <https://us.posthog.com/project/2/insights/abc>", False),
            ("a command", "/remind me how many signups tomorrow", False),
            ("a command for another bot", "!deploy what is in staging", False),
            ("too few words", "anyone??????????", False),
            ("too short", "why?", False),
        ]
    )
    def test_the_word_and_length_checks(self, _name, text, expected):
        event = {"channel_type": "channel", "text": text}

        assert is_untagged_question_candidate(event) is expected
