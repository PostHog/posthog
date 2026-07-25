from __future__ import annotations

import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps

from parameterized import parameterized
from rest_framework import status

from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutNote, SignalScoutRun
from products.skills.backend.models.skills import LLMSkill

SCOUT_SKILL = "signals-scout-error-tracking"


class TestDismissalScoutNotes(APIBaseTest):
    def _state_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/state/"

    def _bulk_state_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/bulk-state/"

    def _create_report(self, title: str = "Checkout errors spiked") -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title=title,
            summary="Test summary",
        )

    def _create_scout_skill(self, name: str = SCOUT_SKILL) -> LLMSkill:
        return LLMSkill.objects.create(team=self.team, name=name, description="test scout", body="# test scout")

    def _create_run(self, *, skill_name: str = SCOUT_SKILL, **overrides) -> SignalScoutRun:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team,
            title="scout run",
            description="scout run",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )
        config, _ = SignalScoutConfig.objects.get_or_create(team=self.team, skill_name=skill_name)
        return SignalScoutRun.objects.create(
            team=self.team,
            task_run=TaskRun.objects.create(task=task, team=self.team),
            scout_config=config,
            skill_name=skill_name,
            skill_version=1,
            **overrides,
        )

    def _dismiss(self, report: SignalReport, **body) -> None:
        response = self.client.post(
            self._state_url(str(report.id)),
            data=json.dumps({"state": "suppressed", **body}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

    def _notes(self) -> list[SignalScoutNote]:
        return list(SignalScoutNote.objects.filter(team=self.team).order_by("created_at"))

    def test_dismissal_note_reaches_the_authoring_scout(self) -> None:
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])

        self._dismiss(report, dismissal_reason="analysis_wrong", dismissal_note="the cited code path is unreachable")

        note = self._notes()[0]
        assert note.skill_name == SCOUT_SKILL
        assert note.origin == SignalScoutNote.Origin.REPORT_DISMISSAL
        assert note.created_by_id == self.user.id
        # The scout needs the verbatim feedback, the reason code, and a way back to the report.
        assert "the cited code path is unreachable" in note.content
        assert "analysis_wrong" in note.content
        assert str(report.id) in note.content
        assert note.expires_at is not None

    @parameterized.expand(
        [
            ("no_authoring_run", False, False),
            ("authoring_scout_skill_no_longer_exists", True, False),
        ]
    )
    def test_note_falls_back_to_the_whole_fleet(self, _name: str, with_run: bool, with_skill: bool) -> None:
        report = self._create_report()
        if with_skill:
            self._create_scout_skill()
        if with_run:
            self._create_run(emitted_report_ids=[str(report.id)])

        self._dismiss(report, dismissal_note="staging noise, ignore this whole class of report")

        # Blank target: a note no scout can be addressed to still has to reach the fleet rather
        # than being dropped on the floor.
        assert [note.skill_name for note in self._notes()] == [""]

    def test_note_is_addressed_to_the_scout_that_edited_a_pipeline_report(self) -> None:
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(edited_report_ids=[str(report.id)])

        self._dismiss(report, dismissal_note="we already know about this one")

        assert [note.skill_name for note in self._notes()] == [SCOUT_SKILL]

    @parameterized.expand(
        [
            ("reason_only", {"dismissal_reason": "already_fixed"}),
            ("blank_note", {"dismissal_reason": "other", "dismissal_note": "   "}),
            ("no_feedback_at_all", {}),
        ]
    )
    def test_no_note_without_prose_to_pass_on(self, _name: str, body: dict) -> None:
        report = self._create_report()

        self._dismiss(report, **body)

        assert self._notes() == []

    @parameterized.expand([("dismiss", "suppressed"), ("snooze", "potential"), ("resolve", "resolved")])
    def test_every_state_that_captures_feedback_promotes_it(self, _name: str, state: str) -> None:
        report = self._create_report()

        response = self.client.post(
            self._state_url(str(report.id)),
            data=json.dumps({"state": state, "dismissal_note": "context the scout should have"}),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(self._notes()) == 1

    def test_bulk_dismissal_writes_one_note_per_scout_not_one_per_report(self) -> None:
        self._create_scout_skill()
        authored = [self._create_report(title=f"Report {index}") for index in range(3)]
        self._create_run(emitted_report_ids=[str(report.id) for report in authored])
        unauthored = self._create_report(title="Pipeline report")

        response = self.client.post(
            self._bulk_state_url(),
            data=json.dumps(
                {
                    "ids": [str(report.id) for report in [*authored, unauthored]],
                    "state": "suppressed",
                    "dismissal_note": "all of these are staging noise",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["transitioned_count"] == 4
        notes = {note.skill_name: note for note in self._notes()}
        assert sorted(notes) == ["", SCOUT_SKILL]
        # The scout's note names every report it authored so the pattern is visible in one read.
        for report in authored:
            assert str(report.id) in notes[SCOUT_SKILL].content
        assert str(unauthored.id) in notes[""].content

    def test_dismissal_still_succeeds_when_the_note_cannot_be_written(self) -> None:
        report = self._create_report()

        with patch("products.signals.backend.dismissal_notes.leave_note", side_effect=RuntimeError("boom")):
            self._dismiss(report, dismissal_note="feedback that never made it to a note")

        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED
        assert self._notes() == []
