from __future__ import annotations

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.discussion_notes import _build_note_content, _extract_question
from products.signals.backend.models import SignalReport
from products.signals.backend.scout_harness.tools.notes import MAX_NOTE_CONTENT_LENGTH

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
            ("single_newline_still_strips_prefix", "Let's discuss this PostHog Inbox report: x\nWhy?", "Why?"),
            ("prefix_with_no_question_returns_blank", "Let's discuss this PostHog Inbox report: x\n\n   ", ""),
        ]
    )
    def test_extract_question(self, _name: str, text: str, expected: str) -> None:
        self.assertEqual(_extract_question(text), expected)

    def test_note_content_fits_a_note_for_an_oversized_question(self) -> None:
        # The API accepts an unbounded description, and a note over MAX_NOTE_CONTENT_LENGTH is
        # rejected by leave_note — which the best-effort boundary would swallow, silently dropping
        # the question. Truncating keeps the note.
        content = _build_note_content(report=SignalReport(title="Checkout errors spiked"), question="why? " * 20_000)
        self.assertLessEqual(len(content), MAX_NOTE_CONTENT_LENGTH)
