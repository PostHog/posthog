from django.test import SimpleTestCase

from parameterized import parameterized

from products.slack_app.backend.logic.untagged_question import is_untagged_question_candidate


class TestIsUntaggedQuestionCandidate(SimpleTestCase):
    @parameterized.expand(
        [
            ("a question that names PostHog", "how many signups does PostHog show for last week?", True),
            ("a request without a question word", "need signups by country from posthog for last month", True),
            ("a statement that names PostHog", "the Post Hog funnel looks off since the deploy", True),
            ("a question that does not name PostHog", "how many people signed up last week?", True),
            ("a question that tags a person", "<@U_ALICE> how many people signed up last week?", True),
            ("a command", "/remind me to check posthog signups tomorrow", False),
            ("a command for another bot", "!deploy posthog to staging now", False),
            ("too few words", "posthog???????????", False),
            ("too short", "posthog?", False),
        ]
    )
    def test_the_word_and_length_checks(self, _name, text, expected):
        event = {"channel_type": "channel", "text": text}

        assert is_untagged_question_candidate(event) is expected
