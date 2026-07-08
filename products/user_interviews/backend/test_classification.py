from django.test import SimpleTestCase

from parameterized import parameterized

from products.user_interviews.backend.classification import derive_auto_classifications
from products.user_interviews.backend.models import UserInterviewClassification


class TestDeriveAutoClassifications(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty transcript has no parseable turns", "", []),
            ("ai only, no user turn", "AI: Hi there, are you free?\n", [UserInterviewClassification.ABANDONED]),
            ("ai only multi line", "AI: Hi.\nAI: Still there?\n", [UserInterviewClassification.ABANDONED]),
            ("blank user turn is not a real turn", "AI: Hello.\nUser:   \n", [UserInterviewClassification.ABANDONED]),
            (
                "lowercase ai-only prefix still abandoned",
                "ai: are you there?\n",
                [UserInterviewClassification.ABANDONED],
            ),
            ("a real exchange is not auto-classified", "AI: How was onboarding?\nUser: Fine, no complaints.", []),
            (
                "unrecognised speaker-heading format is left untagged, not abandoned",
                "#### Speaker 1\nThanks for joining today.\n#### Speaker 2\nHappy to help, this product changed how we work.",
                [],
            ),
        ]
    )
    def test_derive_auto_classifications(self, _name: str, transcript: str, expected: list[str]):
        assert derive_auto_classifications(transcript) == expected
