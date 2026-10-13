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
_ACTION_PROMPT = (
    "A user sent this about the PostHog Inbox report at https://us.posthog.com/project/2/inbox/reports/x. "
    "If it is a question, answer it; if it asks for action, carry the action out and summarize what you did:\n\n"
    "Create the alert this report recommends"
)


class TestExtractQuestion(SimpleTestCase):
    @parameterized.expand(
        [
            ("strips_url_prefix", _PROMPT, None, None, "Is this still happening?"),
            (
                "strips_action_capable_prefix",
                _ACTION_PROMPT,
                None,
                None,
                "Create the alert this report recommends",
            ),
            (
                "strips_answer_this_question_prefix",
                "Answer this question about the PostHog Inbox report at https://x.example/r/1:\n\nIs it fixed?",
                None,
                None,
                "Is it fixed?",
            ),
            (
                "no_prefix_returns_whole",
                "Why does stripe not sync?",
                None,
                None,
                "Why does stripe not sync?",
            ),
            (
                "single_newline_still_strips_prefix",
                "Let's discuss this PostHog Inbox report: x\nWhy?",
                None,
                None,
                "Why?",
            ),
            (
                "prefix_with_no_question_returns_blank",
                "Let's discuss this PostHog Inbox report: x\n\n   ",
                None,
                None,
                "",
            ),
            (
                "desktop_description_returns_question_only",
                "Discuss report: Checkout errors spiked — Is this still happening?",
                "Checkout errors spiked",
                "report-id",
                "Is this still happening?",
            ),
            (
                "desktop_description_without_question_returns_blank",
                "Discuss report: Checkout errors spiked",
                "Checkout errors spiked",
                "report-id",
                "",
            ),
            (
                "desktop_description_with_separator_in_title_returns_question_only",
                "Discuss report: Checkout — errors spiked — Is this still happening?",
                "Checkout — errors spiked",
                "report-id",
                "Is this still happening?",
            ),
            (
                "truncated_desktop_title_without_question_returns_blank",
                f"Discuss report: {'x' * 300}"[:200],
                "x" * 300,
                "report-id",
                "",
            ),
            (
                "desktop_description_truncated_before_question_returns_blank",
                f"Discuss report: {'x' * 182} — why?"[:200],
                "x" * 182,
                "report-id",
                "",
            ),
        ]
    )
    def test_extract_question(
        self,
        _name: str,
        text: str,
        report_title: str | None,
        report_id: str | None,
        expected: str,
    ) -> None:
        self.assertEqual(
            _extract_question(text, report_title=report_title, report_id=report_id),
            expected,
        )

    def test_note_content_fits_a_note_for_an_oversized_question(self) -> None:
        # The API accepts an unbounded description, and a note over MAX_NOTE_CONTENT_LENGTH is
        # rejected by leave_note — which the best-effort boundary would swallow, silently dropping
        # the question. Truncating keeps the note.
        content = _build_note_content(report=SignalReport(title="Checkout errors spiked"), question="why? " * 20_000)
        self.assertLessEqual(len(content), MAX_NOTE_CONTENT_LENGTH)
