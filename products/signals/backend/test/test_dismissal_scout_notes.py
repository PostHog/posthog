from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl
from posthog.scopes import APIScopeObject

from products.signals.backend.artefact_schemas import Dismissal
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutNote,
    SignalScoutRun,
)
from products.skills.backend.models.skills import LLMSkill

SCOUT_SKILL = "signals-scout-error-tracking"
UNFORWARDED_NOTE = "feedback that never made it to a note"


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

    def _dismissal_notes_on(self, report: SignalReport) -> list[str | None]:
        artefacts = SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL
        ).order_by("created_at")
        return [Dismissal.model_validate_json(artefact.content).note for artefact in artefacts]

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

    @parameterized.expand(
        [
            ("dismiss", "suppressed", 1),
            ("snooze", "potential", 1),
            # A resolve says the report did its job, so its note never steers the scout.
            ("resolve", "resolved", 0),
        ]
    )
    def test_only_transitions_that_judge_the_report_are_forwarded(
        self, _name: str, state: str, expected_notes: int
    ) -> None:
        report = self._create_report()

        response = self.client.post(
            self._state_url(str(report.id)),
            data=json.dumps({"state": state, "dismissal_note": "context the scout should have"}),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(self._notes()) == expected_notes
        # The artefact is the record of truth either way, so a resolve still keeps the feedback.
        assert self._dismissal_notes_on(report) == ["context the scout should have"]

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

    def test_restore_out_of_the_archive_is_not_described_as_a_snooze(self) -> None:
        report = self._create_report()
        self._dismiss(report, dismissal_note="archiving for now")
        SignalScoutNote.objects.filter(team=self.team).delete()

        # `state="potential"` on a suppressed report restores it to the status it held before being
        # archived, so the note must not tell the scout its report was snoozed.
        response = self.client.post(
            self._state_url(str(report.id)),
            data=json.dumps({"state": "potential", "dismissal_note": "back to ready, this is real"}),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY
        content = self._notes()[0].content
        assert "restored to ready" in content
        assert "snoozed" not in content

    def test_dismissal_still_succeeds_when_the_note_cannot_be_written(self) -> None:
        report = self._create_report()

        with patch("products.signals.backend.dismissal_notes.leave_note", side_effect=RuntimeError("boom")):
            self._dismiss(report, dismissal_note=UNFORWARDED_NOTE)

        self._assert_dismissed_without_a_note(report)

    def test_dismissal_still_succeeds_when_authorization_blows_up(self) -> None:
        # The boundary has to wrap authorization too, which reads the database.
        def boom() -> bool:
            raise RuntimeError("boom")

        report = self._create_report()

        with self._llm_skill_access(boom):
            self._dismiss(report, dismissal_note=UNFORWARDED_NOTE)

        self._assert_dismissed_without_a_note(report)

    @contextmanager
    def _llm_skill_access(self, outcome: Callable[[], bool]) -> Iterator[None]:
        """Replace only the `llm_skill` leg of the access check.

        Scoped to one resource because DRF's permission pass runs through this same method first,
        so replacing it wholesale fails the request before the view runs.
        """
        real_check = UserAccessControl.check_access_level_for_resource

        def replacement(self_: UserAccessControl, resource: APIScopeObject, required_level: AccessControlLevel) -> bool:
            if resource == "llm_skill":
                return outcome()
            return real_check(self_, resource, required_level)

        with patch.object(UserAccessControl, "check_access_level_for_resource", autospec=True, side_effect=replacement):
            yield

    def _assert_dismissed_without_a_note(self, report: SignalReport) -> None:
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED
        assert self._notes() == []
        assert self._dismissal_notes_on(report) == [UNFORWARDED_NOTE]

    def test_no_note_for_a_child_environment_report(self) -> None:
        # The note would land on the parent project, readable by people who may have no access to
        # the environment the report lives on, so a child environment's feedback stays on the report.
        environment = Team.objects.create(
            organization=self.organization, parent_team=self.team, name="Child environment"
        )
        report = SignalReport.objects.create(
            team=environment, status=SignalReport.Status.READY, title="Child report", summary="Test summary"
        )

        response = self.client.post(
            f"/api/projects/{environment.id}/signals/reports/{report.id}/state/",
            data=json.dumps({"state": "suppressed", "dismissal_note": "noise from the staging env"}),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED
        assert not SignalScoutNote.all_teams.exists()

    def test_no_note_when_the_token_is_scoped_to_a_child_environment(self) -> None:
        # Notes canonicalize to the parent project, so a token confined to a child environment must
        # not steer the parent's scouts through a dismissal, even though its user has parent access.
        environment = Team.objects.create(
            organization=self.organization, parent_team=self.team, name="Child environment"
        )
        report = SignalReport.objects.create(
            team=environment, status=SignalReport.Status.READY, title="Child report", summary="Test summary"
        )
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Child-scoped key",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["task:write", "task:read"],
            scoped_teams=[environment.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")

        response = self.client.post(
            f"/api/projects/{environment.id}/signals/reports/{report.id}/state/",
            data=json.dumps({"state": "suppressed", "dismissal_note": "steering the parent's fleet"}),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED
        # `all_teams` so the assertion holds wherever the row would have landed.
        assert not SignalScoutNote.all_teams.exists()

    def test_no_note_when_the_dismisser_may_not_steer_scouts(self) -> None:
        # Forwarding re-checks the `llm_skill` editor bar that `SignalScoutNoteViewSet` requires, so a
        # member an admin restricted from skill editing can't reach the steering channel by
        # dismissing instead.
        report = self._create_report()

        with self._llm_skill_access(lambda: False):
            self._dismiss(report, dismissal_reason="wontfix_irrelevant", dismissal_note="not worth it")

        # The dismissal still stands and the artefact still records the feedback.
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED
        assert self._notes() == []
