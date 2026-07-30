from __future__ import annotations

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.discussion_notes import _extract_question

_PROMPT = (
    "Let's discuss this PostHog Inbox report: https://us.posthog.com/project/2/inbox/reports/x\n\n"
    "Is this still happening?"
)


class TestExtractQuestion(SimpleTestCase):
    # The forwarded note should quote only the user's question, not the URL-prefixed kickoff prompt,
    # and degrade to the whole text if the frontend prompt format ever drifts. Behavior that reaches
    # the scout (targeting, auth gating, best-effort) is covered end to end in the tasks API tests.
    @parameterized.expand(
        [
            ("strips_url_prefix", _PROMPT, "Is this still happening?"),
            ("no_prefix_returns_whole", "Why does stripe not sync?", "Why does stripe not sync?"),
            ("prefix_without_blank_line_returns_whole", "Let's discuss this PostHog Inbox report: x", None),
        ]
    )
    def test_extract_question(self, _name: str, text: str, expected: str | None) -> None:
        self.assertEqual(_extract_question(text), expected if expected is not None else text.strip())
