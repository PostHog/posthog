from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.rbac.user_access_control import UserAccessControl

from products.signals.backend.discussion_notes import _extract_question, forward_discussion_note
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutNote, SignalScoutRun
from products.skills.backend.models.skills import LLMSkill

SCOUT_SKILL = "signals-scout-error-tracking"
_PROMPT = (
    "Let's discuss this PostHog Inbox report: https://us.posthog.com/project/2/inbox/reports/x\n\n"
    "Is this still happening?"
)


class TestExtractQuestion(SimpleTestCase):
    @parameterized.expand(
        [
            ("strips_url_prefix", _PROMPT, "Is this still happening?"),
            ("no_prefix_returns_whole", "Why does stripe not sync?", "Why does stripe not sync?"),
            ("prefix_without_blank_line_returns_whole", "Let's discuss this PostHog Inbox report: x", None),
        ]
    )
    def test_extract_question(self, _name: str, text: str, expected: str | None) -> None:
        self.assertEqual(_extract_question(text), expected if expected is not None else text.strip())


class TestForwardDiscussionNote(APIBaseTest):
    def _create_report(self, title: str = "Checkout errors spiked") -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title=title)

    def _record_authoring_run(self, report: SignalReport, *, skill_name: str = SCOUT_SKILL) -> None:
        # Emit-time authorship is read off the scout's run rows (see `_target_skill_names`).
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team, title="scout run", description="scout run", origin_product=Task.OriginProduct.SIGNALS_SCOUT
        )
        config, _ = SignalScoutConfig.objects.get_or_create(team=self.team, skill_name=skill_name)
        SignalScoutRun.objects.create(
            team=self.team,
            task_run=TaskRun.objects.create(task=task, team=self.team),
            scout_config=config,
            skill_name=skill_name,
            skill_version=1,
            emitted_report_ids=[str(report.id)],
        )

    def _request(self) -> Request:
        # Session-style request: no API-key authenticator, so `_may_steer_scouts` reduces to the RBAC
        # editor bar the default test user clears — the same gate the dismissal forwarder uses.
        drf = Request(APIRequestFactory().post("/"))
        drf._authenticator = None
        drf.user = self.user
        return drf

    def _forward(self, report: SignalReport, text: str = _PROMPT) -> str | None:
        return forward_discussion_note(team=self.team, report_id=str(report.id), text=text, request=self._request())

    def test_forwards_question_targeted_at_authoring_scout(self) -> None:
        report = self._create_report()
        LLMSkill.objects.create(team=self.team, name=SCOUT_SKILL, description="scout", body="# scout")
        self._record_authoring_run(report)

        note_id = self._forward(report)
        assert note_id is not None

        note = SignalScoutNote.objects.get(id=note_id)
        self.assertEqual(note.origin, SignalScoutNote.Origin.REPORT_DISCUSSION)
        self.assertEqual(note.skill_name, SCOUT_SKILL)
        self.assertEqual(note.created_by_id, self.user.id)
        assert note.expires_at is not None
        self.assertTrue(note.expires_at > timezone.now())
        self.assertIn("Is this still happening?", note.content)
        self.assertIn(str(report.id), note.content)
        # Only the question is quoted, not the URL-prefixed kickoff prompt.
        self.assertNotIn("https://us.posthog.com", note.content)

    def test_falls_back_to_fleet_when_no_authoring_run(self) -> None:
        report = self._create_report()

        note_id = self._forward(report)
        assert note_id is not None
        note = SignalScoutNote.objects.get(id=note_id)

        self.assertEqual(note.skill_name, "")

    def test_does_not_forward_when_user_lacks_skill_editor_access(self) -> None:
        report = self._create_report()

        with patch.object(UserAccessControl, "check_access_level_for_resource", return_value=False):
            self.assertIsNone(self._forward(report))
        self.assertFalse(SignalScoutNote.objects.filter(team=self.team).exists())

    def test_best_effort_swallows_note_write_failure(self) -> None:
        report = self._create_report()

        with patch("products.signals.backend.discussion_notes.leave_note", side_effect=RuntimeError("boom")):
            self.assertIsNone(self._forward(report))
        self.assertFalse(SignalScoutNote.objects.filter(team=self.team).exists())

    def test_skips_blank_question(self) -> None:
        report = self._create_report()

        self.assertIsNone(self._forward(report, text="Let's discuss this PostHog Inbox report: x\n\n   "))
        self.assertFalse(SignalScoutNote.objects.filter(team=self.team).exists())
