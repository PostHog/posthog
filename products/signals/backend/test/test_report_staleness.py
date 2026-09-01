from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import NoteArtefact
from products.signals.backend.implementation_pr import ImplementationPr
from products.signals.backend.models import (
    REAPABLE_REPORT_STATUSES,
    SignalReport,
    SignalReportAction,
    SignalReportArtefact,
    SignalTeamConfig,
)
from products.signals.backend.report_staleness import (
    MAX_ARCHIVES_PER_SWEEP,
    SCOUT_REPORT_HUMAN_SILENCE,
    STALE_DISMISSAL_REASON,
    STALE_REPORT_AGE,
    sweep_stale_reports,
)

_PR_STATE = "products.signals.backend.report_staleness.fetch_implementation_pr_state_for_reports"
_FLAG = "products.signals.backend.report_staleness.posthoganalytics.feature_enabled"
_CLOSE_TASK = "products.signals.backend.receivers.close_dismissed_report_pr"


@override_settings(SIGNAL_STALE_REPORT_REAPER_ENABLED=True)
class TestStaleReportSweep(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        SignalTeamConfig.objects.update_or_create(team=self.team, defaults={"stale_report_sweep_enabled": True})

    def _report(
        self,
        *,
        status: str = SignalReport.Status.READY,
        activity_days_ago: int = 0,
        human_days_ago: int | None = None,
        content_revision_count: int = 0,
    ) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team,
            status=status,
            title="Report",
            summary="Summary",
            signal_count=1,
            total_weight=1.0,
            content_revision_count=content_revision_count,
        )
        SignalReport.objects.filter(id=report.id).update(
            last_activity_at=self.now - timedelta(days=activity_days_ago),
            last_human_touch_at=None if human_days_ago is None else self.now - timedelta(days=human_days_ago),
        )
        report.refresh_from_db()
        return report

    def _sweep(self, pr_state: dict | None = None):
        with (
            patch(_PR_STATE, return_value=pr_state or {}),
            patch(_FLAG, return_value=True),
            patch(_CLOSE_TASK),
        ):
            return sweep_stale_reports(now=self.now)

    def _status_of(self, report: SignalReport) -> str:
        report.refresh_from_db()
        return report.status

    # ── The clock split ──────────────────────────────────────────────────────────────────────
    # The reason this PR has two clocks at all: a scout keeps its reports looking active forever,
    # so an inactivity rule never fires on exactly the reports that need archiving. Collapsing the
    # two arms back into one would pass every other test in this file.

    def test_a_scout_revised_report_nobody_looked_at_is_archived_on_human_silence(self) -> None:
        stale = self._report(
            content_revision_count=30,
            activity_days_ago=0,
            human_days_ago=SCOUT_REPORT_HUMAN_SILENCE.days + 1,
        )
        outcome = self._sweep()
        assert [str(c.report.id) for c in outcome.archived] == [str(stale.id)]
        assert outcome.archived[0].clock == "human_silence"
        assert self._status_of(stale) == SignalReport.Status.SUPPRESSED

    def test_a_scout_revised_report_someone_looked_at_recently_is_left_alone(self) -> None:
        looked_at = self._report(content_revision_count=30, activity_days_ago=0, human_days_ago=5)
        outcome = self._sweep()
        assert outcome.detected == []
        assert self._status_of(looked_at) == SignalReport.Status.READY

    def test_a_scout_revised_report_is_not_judged_on_inactivity(self) -> None:
        # Idle far past the inactivity window, but a person was here yesterday. The inactivity arm
        # would archive it; the human-silence arm is the only one that may judge it.
        revised = self._report(
            content_revision_count=1,
            activity_days_ago=STALE_REPORT_AGE.days + 30,
            human_days_ago=1,
        )
        outcome = self._sweep()
        assert outcome.detected == []
        assert self._status_of(revised) == SignalReport.Status.READY

    def test_a_pipeline_report_is_not_judged_on_human_silence(self) -> None:
        # Nobody has ever touched it, but the pipeline moved it today. Only the inactivity arm may
        # judge a report no scout has rewritten.
        active = self._report(content_revision_count=0, activity_days_ago=1, human_days_ago=None)
        outcome = self._sweep()
        assert outcome.detected == []
        assert self._status_of(active) == SignalReport.Status.READY

    def test_a_pipeline_report_that_stopped_moving_is_archived_on_inactivity(self) -> None:
        stale = self._report(content_revision_count=0, activity_days_ago=STALE_REPORT_AGE.days + 1)
        outcome = self._sweep()
        assert [str(c.report.id) for c in outcome.archived] == [str(stale.id)]
        assert outcome.archived[0].clock == "inactivity"

    def test_an_untouched_clock_is_judged_from_the_report_birth(self) -> None:
        # A null clock is the common case on the human arm: most reports nobody ever opened. Left
        # unjudged, the arm would never fire on them at all.
        report = self._report(content_revision_count=2, activity_days_ago=0, human_days_ago=None)
        SignalReport.objects.filter(id=report.id).update(
            created_at=self.now - timedelta(days=SCOUT_REPORT_HUMAN_SILENCE.days + 1)
        )
        outcome = self._sweep()
        assert [str(c.report.id) for c in outcome.archived] == [str(report.id)]

    # ── What may be archived ─────────────────────────────────────────────────────────────────

    @parameterized.expand([(status,) for status in SignalReport.Status.values])
    def test_only_reapable_statuses_are_archived(self, status: str) -> None:
        self._report(status=status, activity_days_ago=STALE_REPORT_AGE.days + 1)
        outcome = self._sweep()
        assert bool(outcome.archived) is (status in REAPABLE_REPORT_STATUSES)

    def test_a_report_whose_pr_merged_is_never_archived(self) -> None:
        shipped = self._report(activity_days_ago=STALE_REPORT_AGE.days + 1)
        outcome = self._sweep(
            pr_state={str(shipped.id): ImplementationPr(url="https://github.com/o/r/pull/1", merged=True)}
        )
        assert outcome.detected == []
        assert self._status_of(shipped) == SignalReport.Status.READY

    def test_a_report_with_an_open_pr_is_archived_and_flagged_as_having_one(self) -> None:
        report = self._report(activity_days_ago=STALE_REPORT_AGE.days + 1)
        outcome = self._sweep(
            pr_state={str(report.id): ImplementationPr(url="https://github.com/o/r/pull/1", merged=False)}
        )
        assert [c.has_open_pr for c in outcome.archived] == [True]

    def test_archiving_records_a_stale_dismissal_and_closes_the_pr(self) -> None:
        report = self._report(activity_days_ago=STALE_REPORT_AGE.days + 3)
        with (
            patch(_PR_STATE, return_value={}),
            patch(_FLAG, return_value=True),
            patch(_CLOSE_TASK) as close_task,
            self.captureOnCommitCallbacks(execute=True),
        ):
            sweep_stale_reports(now=self.now)
        dismissal = SignalReportArtefact.objects.get(
            report_id=report.id, type=SignalReportArtefact.ArtefactType.DISMISSAL
        )
        assert STALE_DISMISSAL_REASON in dismissal.content
        close_task.delay.assert_called_once_with(
            report_id=str(report.id), team_id=self.team.id, reason=STALE_DISMISSAL_REASON
        )

    # ── The gates ────────────────────────────────────────────────────────────────────────────
    # All three default closed. A gate that stops blocking archives a customer's whole backlog on
    # the deploy that drops it, so each is asserted on its own.

    def test_each_gate_blocks_archiving_on_its_own_while_detection_continues(self) -> None:
        for gate in ("setting", "flag", "team"):
            with self.subTest(gate=gate):
                report = self._report(activity_days_ago=STALE_REPORT_AGE.days + 1)
                SignalTeamConfig.objects.filter(team=self.team).update(
                    stale_report_sweep_enabled=False if gate == "team" else True
                )
                with (
                    patch(_PR_STATE, return_value={}),
                    patch(_FLAG, return_value=gate != "flag"),
                    patch(_CLOSE_TASK),
                    override_settings(SIGNAL_STALE_REPORT_REAPER_ENABLED=gate != "setting"),
                ):
                    outcome = sweep_stale_reports(now=self.now)
                assert len(outcome.detected) == 1
                assert outcome.archived == []
                assert outcome.gated == 1
                assert self._status_of(report) == SignalReport.Status.READY
                report.delete()

    def test_a_team_that_never_set_the_opt_in_is_swept(self) -> None:
        SignalTeamConfig.objects.filter(team=self.team).update(stale_report_sweep_enabled=None)
        report = self._report(activity_days_ago=STALE_REPORT_AGE.days + 1)
        outcome = self._sweep()
        assert [str(c.report.id) for c in outcome.archived] == [str(report.id)]

    # ── Blast radius ─────────────────────────────────────────────────────────────────────────

    def test_the_archive_cap_bounds_one_sweep_and_reports_what_it_deferred(self) -> None:
        with patch("products.signals.backend.report_staleness.MAX_ARCHIVES_PER_SWEEP", 2):
            for _ in range(4):
                self._report(activity_days_ago=STALE_REPORT_AGE.days + 1)
            outcome = self._sweep()
        assert len(outcome.archived) == 2
        assert outcome.deferred == 2
        assert MAX_ARCHIVES_PER_SWEEP > 0


class TestStalenessClockStamps(BaseTest):
    """What moves each clock. The sweep is only as good as the evidence it reads."""

    def _report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
        )

    def test_a_machine_artefact_moves_activity_but_never_the_human_clock(self) -> None:
        # The whole human-silence arm rests on this: if a pipeline or scout write could move
        # `last_human_touch_at`, a scout would keep its own reports alive forever and the arm would
        # never fire on the reports it exists for.
        report = self._report()
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=NoteArtefact(note="a scout says this still holds"),
            attribution=ArtefactAttribution.system(),
        )
        report.refresh_from_db()
        assert report.last_human_touch_at is None

    def test_a_person_attributed_artefact_moves_both_clocks(self) -> None:
        report = self._report()
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=NoteArtefact(note="looking into this"),
            attribution=ArtefactAttribution.from_user(self.user.id),
        )
        report.refresh_from_db()
        assert report.last_human_touch_at is not None
        assert report.last_activity_at is not None

    def test_opening_a_report_counts_as_a_human_touch(self) -> None:
        report = self._report()
        SignalReportAction.record(
            team_id=self.team.id,
            report_id=str(report.id),
            user_id=self.user.id,
            action_type=SignalReportAction.ActionType.VIEW,
        )
        report.refresh_from_db()
        assert report.last_human_touch_at is not None

    def test_every_status_transition_restarts_the_activity_clock(self) -> None:
        # A report restored from the archive, or promoted out of `potential`, re-enters a reapable
        # status. Without this it would carry a clock that never started and be archived again by
        # the very next sweep.
        report = self._report()
        SignalReport.objects.filter(id=report.id).update(last_activity_at=timezone.now() - timedelta(days=90))
        report.refresh_from_db()
        report.save(update_fields=report.transition_to(SignalReport.Status.SUPPRESSED))
        report.save(update_fields=report.transition_to(SignalReport.Status.READY))
        report.refresh_from_db()
        assert report.last_activity_at is not None
        assert timezone.now() - report.last_activity_at < timedelta(minutes=1)
