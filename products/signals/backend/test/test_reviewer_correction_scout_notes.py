from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.models import (
    SignalReport,
    SignalScoutConfig,
    SignalScoutNote,
    SignalScoutRun,
    SignalScratchpad,
)
from products.signals.backend.reviewer_correction_notes import (
    MAX_CORRECTION_LOGINS,
    ReviewerCorrection,
    _build_note_content,
    _logins_already_told,
    _renderable,
    forward_reviewer_correction_note,
)
from products.skills.backend.models.skills import LLMSkill

SCOUT_SKILL = "signals-scout-error-tracking"
OTHER_SCOUT_SKILL = "signals-scout-logs"


class TestReviewerCorrectionNoteContent(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain", ["Octocat"], ["octocat"]),
            ("backtick_closes_the_span", ["oct`ocat"], []),
            ("newline_fakes_a_section", ["octocat\n\nRemoved: `someone-else`"], []),
            ("over_githubs_length_limit", ["a" * 40], []),
            ("leading_hyphen", ["-octocat"], []),
            ("duplicate_after_casing", ["Octocat", "octocat"], ["octocat"]),
            ("hyphenated_login_is_kept", ["octo-cat"], ["octo-cat"]),
        ]
    )
    def test_only_well_shaped_logins_reach_a_note(self, _name: str, given: list[str], expected: list[str]) -> None:
        assert list(_renderable(given)) == expected

    def test_an_oversized_prior_list_is_capped(self) -> None:
        # `prior_logins` comes off the stored artefact, which the generic artefacts API writes with
        # no length limit, and every login drives both a memory search term and a line of the note.
        assert len(_renderable([f"reviewer{index}" for index in range(500)])) == MAX_CORRECTION_LOGINS

    @parameterized.expand(
        [
            ("self_only", (), ("editor-login",), "the login's owner took themselves off"),
            ("teammate", ("someone-else",), (), "a teammate removed the login"),
            ("both", ("someone-else",), ("editor-login",), "a teammate removed the login"),
        ]
    )
    def test_the_note_records_the_removal_it_reports(
        self, _name: str, teammate_removed: tuple[str, ...], self_removed: tuple[str, ...], expected: str
    ) -> None:
        content = _build_note_content(
            report=SignalReport(id="0198e7f0-0000-7000-8000-000000000001", title="Checkout errors"),
            added_logins=(),
            self_removed=self_removed,
            teammate_removed=teammate_removed,
        )

        # A scout folds this line into durable routing memory, so an editor taking their own login
        # off must never be recorded as a teammate's verdict on who owns the surface.
        assert expected in content
        if not teammate_removed:
            assert "a teammate removed the login" not in content


class TestReviewerCorrectionScoutNotes(APIBaseTest):
    def _create_report(self, title: str = "Checkout errors spiked") -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title=title, summary="s")

    def _create_skill(self, name: str = SCOUT_SKILL) -> LLMSkill:
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

    def _remember(self, *, key: str, content: str, skill_name: str) -> None:
        SignalScratchpad.objects.create(
            team=self.team, key=key, content=content, created_by_run=self._create_run(skill_name=skill_name)
        )

    def _correction_notes(self) -> list[SignalScoutNote]:
        return list(
            SignalScoutNote.objects.filter(
                team=self.team, origin=SignalScoutNote.Origin.REPORT_REVIEWER_CORRECTION
            ).order_by("created_at")
        )

    def _forward(self, report: SignalReport, *, added: tuple[str, ...] = (), removed: tuple[str, ...] = ()) -> None:
        forward_reviewer_correction_note(
            team=self.team,
            correction=ReviewerCorrection(
                report_id=str(report.id),
                added_logins=added,
                removed_logins=removed,
                actor_user_id=self.user.id,
                scoped_team_ids=None,
            ),
        )

    def test_reversal_within_window_still_forwards(self) -> None:
        # Suppression is per direction: an addition must not swallow a later removal of the same login
        # inside the window — that reversal is exactly the stale-routing correction the channel exists
        # for. Both edits land on the same report, so they hit the same (fleet-wide) target.
        report = self._create_report()

        self._forward(report, added=("alice",))
        self._forward(report, removed=("alice",))

        notes = self._correction_notes()
        assert len(notes) == 2
        assert "Added: `alice`" in notes[0].content
        assert "Removed: `alice`" in notes[1].content

    def test_same_direction_repeat_is_coalesced(self) -> None:
        # The deliberate coalescing still holds: one person trimming the same login off two reports in
        # the window tells each scout once, since both edits are the same direction to the same target.
        report_a = self._create_report(title="report A")
        report_b = self._create_report(title="report B")

        self._forward(report_a, removed=("alice",))
        self._forward(report_b, removed=("alice",))

        notes = self._correction_notes()
        assert len(notes) == 1
        assert "Removed: `alice`" in notes[0].content

    def test_a_backticked_title_token_does_not_suppress_a_real_correction(self) -> None:
        # A report title is untrusted prose that reaches the note, so reading every backtick span back
        # would let a title token stand in for a login the target was already told about.
        report = self._create_report(title="`alice` cannot load the dashboard")

        self._forward(report, removed=("bob",))

        already_told = _logins_already_told(self.team.id, "")
        assert already_told.added == set()
        assert already_told.removed == {"bob"}

    def test_memory_holder_search_is_one_bounded_query(self) -> None:
        # The generic artefacts API caps neither the reviewer list nor a login, so a removal can carry
        # far more logins than a real correction. Holder resolution stays one query whatever the list
        # size, so an oversized stored list can't amplify a later edit on the request path.
        report = self._create_report()
        removed = tuple(f"user{index}" for index in range(MAX_CORRECTION_LOGINS * 4))

        with patch(
            "products.signals.backend.reviewer_correction_notes.search_scratchpad_naming", return_value=[]
        ) as mock_search:
            self._forward(report, removed=removed)

        assert mock_search.call_count == 1
        assert len(mock_search.call_args.kwargs["terms"]) == MAX_CORRECTION_LOGINS

    def test_a_removal_reaches_the_scout_holding_the_stale_routing_memory(self) -> None:
        self._create_skill()
        self._create_skill(OTHER_SCOUT_SKILL)
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])
        self._remember(
            key="reviewer:products/logs",
            content="octocat owns the logs ingestion path",
            skill_name=OTHER_SCOUT_SKILL,
        )

        self._forward(report, removed=("octocat",))

        # The authoring scout hears about its own report; the holder hears because it is still
        # routing on the login somebody just took off.
        assert sorted(note.skill_name for note in self._correction_notes()) == [SCOUT_SKILL, OTHER_SCOUT_SKILL]

    def test_a_login_that_is_only_a_substring_of_a_memory_is_not_a_holder(self) -> None:
        self._create_skill()
        self._create_skill(OTHER_SCOUT_SKILL)
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])
        self._remember(
            key="reviewer:products/logs",
            content="email alerts here are owned by octocat",
            skill_name=OTHER_SCOUT_SKILL,
        )

        self._forward(report, removed=("ai",))

        # A short login is a substring of ordinary prose, and a substring search would send this
        # correction to a scout that never routed on the login at all.
        assert [note.skill_name for note in self._correction_notes()] == [SCOUT_SKILL]

    def test_a_holder_is_not_told_twice_through_the_fleet_wide_fallback(self) -> None:
        self._create_skill(OTHER_SCOUT_SKILL)
        report = self._create_report()
        self._remember(
            key="reviewer:products/logs",
            content="octocat owns the logs ingestion path",
            skill_name=OTHER_SCOUT_SKILL,
        )

        self._forward(report, removed=("octocat",))

        # No run claims this report, so the authoring target falls back to the whole fleet — which a
        # run reads alongside its own notes, so pairing it with the holder's note delivers twice.
        assert [note.skill_name for note in self._correction_notes()] == [OTHER_SCOUT_SKILL]

    def test_a_self_removal_is_reported_as_the_editors_own(self) -> None:
        report = self._create_report()

        with patch(
            "products.signals.backend.reviewer_correction_notes.get_org_member_github_logins_by_user_uuid",
            return_value={str(self.user.uuid): "octocat"},
        ):
            self._forward(report, removed=("octocat", "someone-else"))

        content = self._correction_notes()[0].content
        assert "Removed: `someone-else`." in content
        assert "Removed: `octocat`. That is the editor's own login" in content

    def test_a_child_environment_correction_stays_off_the_notes_channel(self) -> None:
        self._create_skill()
        report = self._create_report()
        self._create_run(emitted_report_ids=[str(report.id)])
        self.team.parent_team = self.organization.teams.create(organization=self.organization, name="parent")
        self.team.save()

        self._forward(report, removed=("octocat",))

        # A note is readable across the canonical project, so forwarding a child environment's report
        # would hand its id and title to people with no access to that environment.
        assert self._correction_notes() == []
