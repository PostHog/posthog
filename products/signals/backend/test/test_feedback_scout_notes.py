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
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.signals.backend.models import (
    SignalReport,
    SignalReportAction,
    SignalScoutConfig,
    SignalScoutNote,
    SignalScoutRun,
)
from products.skills.backend.models.skills import LLMSkill

SCOUT_SKILL = "signals-scout-error-tracking"


class TestFeedbackScoutNotes(APIBaseTest):
    def _feedback_url(self, report_id: str, team_id: int | None = None) -> str:
        return f"/api/projects/{team_id or self.team.id}/signals/reports/{report_id}/feedback/"

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

    def _feedback(self, report: SignalReport, *, team_id: int | None = None, **body) -> dict:
        response = self.client.post(
            self._feedback_url(str(report.id), team_id=team_id),
            data=json.dumps(body),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _notes(self) -> list[SignalScoutNote]:
        return list(SignalScoutNote.objects.filter(team=self.team).order_by("created_at"))

    def test_feedback_note_reaches_the_authoring_scout(self) -> None:
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])

        body = self._feedback(report, sentiment="positive", note="the repro steps were exactly right")

        assert body["forwarded"] is True
        note = self._notes()[0]
        assert note.skill_name == SCOUT_SKILL
        assert note.origin == SignalScoutNote.Origin.REPORT_FEEDBACK
        assert note.created_by_id == self.user.id
        assert "the repro steps were exactly right" in note.content
        assert "found useful" in note.content
        assert str(report.id) in note.content
        assert note.expires_at is not None
        # Feedback never changes the report's state — it only carries the note to the scout.
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    def test_negative_sentiment_reads_as_not_useful(self) -> None:
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])

        self._feedback(report, sentiment="negative", note="this was already fixed weeks ago")

        assert "did not find useful" in self._notes()[0].content

    def test_note_is_addressed_to_the_scout_that_edited_a_pipeline_report(self) -> None:
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(edited_report_ids=[str(report.id)])

        self._feedback(report, sentiment="positive", note="good catch on the follow-up")

        assert [note.skill_name for note in self._notes()] == [SCOUT_SKILL]

    def test_feedback_reaches_a_suppressed_report(self) -> None:
        # The Dismissed tab renders the same detail view, thumbs rating included, so feedback must
        # resolve a suppressed report by ID instead of 404ing like mutating-by-ID actions do.
        self._create_scout_skill()
        report = self._create_report()
        report.status = SignalReport.Status.SUPPRESSED
        report.save()
        self._create_run(emitted_report_ids=[str(report.id)])

        body = self._feedback(report, sentiment="negative", note="dismissed because it was stale on arrival")

        assert body["forwarded"] is True
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED

    @parameterized.expand(
        [
            ("no_authoring_run", False, False),
            ("authoring_scout_skill_no_longer_exists", True, False),
        ]
    )
    def test_no_note_for_a_report_with_no_authoring_scout(self, _name: str, with_run: bool, with_skill: bool) -> None:
        # Unlike a dismissal, feedback is not fleet-broadcast: with no scout to address, the verdict
        # would be noise, so nothing is forwarded (but the request still succeeds).
        report = self._create_report()
        if with_skill:
            self._create_scout_skill()
        if with_run:
            self._create_run(emitted_report_ids=[str(report.id)])

        body = self._feedback(report, sentiment="negative", note="not useful, but no scout owns this")

        assert body["forwarded"] is False
        assert self._notes() == []

    @parameterized.expand([("blank", "   "), ("missing", None)])
    def test_a_bare_rating_records_the_action_without_forwarding(self, _name: str, note: str | None) -> None:
        # The bare thumb carries no note to forward, but the rating itself is consumption
        # evidence the inactivity sweep reads — it must persist as a report action, not 400.
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])

        if note is not None:
            body = self._feedback(report, sentiment="positive", note=note)
        else:
            body = self._feedback(report, sentiment="positive")
        assert body["forwarded"] is False

        assert self._notes() == []
        action = SignalReportAction.objects.get(report=report, user=self.user)
        assert action.type == SignalReportAction.ActionType.FEEDBACK
        assert action.metadata == {"sentiment": "positive"}

    def test_repeat_ratings_collapse_to_one_action_with_the_latest_sentiment(self) -> None:
        # One row per person per report: a changed mind bumps the row and rewrites the sentiment
        # rather than accumulating contradictory evidence rows.
        report = self._create_report()

        self._feedback(report, sentiment="positive")
        self._feedback(report, sentiment="negative")

        action = SignalReportAction.objects.get(report=report, user=self.user)
        assert action.count == 2
        assert action.metadata == {"sentiment": "negative"}

    def test_a_note_following_a_rating_counts_as_one_interaction(self) -> None:
        # The inbox posts the bare rating on click and the optional note afterwards — one thumb
        # choice. The note request must amend the action row, not count a second interaction.
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])

        self._feedback(report, sentiment="positive")
        self._feedback(report, sentiment="positive", note="the staging spike is a known issue")

        action = SignalReportAction.objects.get(report=report, user=self.user)
        assert action.count == 1
        assert action.metadata == {"sentiment": "positive"}
        assert len(self._notes()) == 1

    def test_a_note_carrying_rating_with_no_prior_row_still_records_the_action(self) -> None:
        # A client may send rating and note in one request; skipping the count bump must not
        # skip creating the consumption record itself.
        report = self._create_report()

        self._feedback(report, sentiment="negative", note="not useful")

        action = SignalReportAction.objects.get(report=report, user=self.user)
        assert action.count == 1
        assert action.metadata == {"sentiment": "negative"}

    def test_feedback_still_succeeds_when_the_note_cannot_be_written(self) -> None:
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])

        with patch("products.signals.backend.feedback_notes.leave_note", side_effect=RuntimeError("boom")):
            body = self._feedback(report, sentiment="positive", note="the analytics event still recorded this")

        assert body["forwarded"] is False
        assert self._notes() == []
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    def test_no_note_for_a_child_environment_report(self) -> None:
        # Notes canonicalize to the parent project, so a child environment's feedback must not reach
        # the parent's scouts.
        environment = Team.objects.create(
            organization=self.organization, parent_team=self.team, name="Child environment"
        )
        self._create_scout_skill()
        report = SignalReport.objects.create(
            team=environment, status=SignalReport.Status.READY, title="Child report", summary="Test summary"
        )
        self._create_run(emitted_report_ids=[str(report.id)])

        body = self._feedback(report, team_id=environment.id, sentiment="positive", note="steering the parent fleet")

        assert body["forwarded"] is False
        assert not SignalScoutNote.all_teams.exists()

    def test_no_note_when_the_token_lacks_the_note_scopes(self) -> None:
        # The feedback text has no second path to a run, so — like a discussion — forwarding demands
        # the note-write key scopes on top of the `task:write` the action itself needs.
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Task-only key",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["task:write", "task:read"],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")

        body = self._feedback(report, sentiment="negative", note="a task token should not steer the fleet")

        assert body["forwarded"] is False
        assert not SignalScoutNote.all_teams.exists()

    def test_no_note_when_the_rater_may_not_steer_scouts(self) -> None:
        # Forwarding re-checks the `llm_skill` editor bar the notes API requires, so a member barred
        # from skill editing can't reach the steering channel through feedback.
        self._create_scout_skill()
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])

        with self._llm_skill_access(lambda: False):
            body = self._feedback(report, sentiment="positive", note="not allowed to steer")

        assert body["forwarded"] is False
        assert self._notes() == []

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
