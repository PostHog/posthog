from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import Dismissal, RelatedTo
from products.signals.backend.models import SignalReport, SignalReportArtefact

COMMAND_MODULE_PATH = "products.signals.backend.management.commands.backfill_fixed_dismissal_forks"
DISMISSED_AGE = timedelta(days=30)


class TestBackfillFixedDismissalForks(BaseTest):
    def _dismissed_report(self, reason: str) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.SUPPRESSED,
            status_before_suppression=SignalReport.Status.READY,
            title="stale chunk TypeErrors",
            summary="original summary",
        )
        dismissal = SignalReportArtefact.append_dismissal(
            team_id=self.team.id,
            report_id=str(report.id),
            content=Dismissal(reason=reason),
            attribution=ArtefactAttribution.system(),
        )
        # Backdated so "signals since the dismissal" has a window to fall in. `.update()` bypasses
        # auto_now_add.
        SignalReportArtefact.objects.filter(id=dismissal.id).update(created_at=timezone.now() - DISMISSED_AGE)
        return report

    def _signals(self, count: int, *, age: timedelta) -> list[dict]:
        return [{"timestamp": timezone.now() - age, "weight": 0.5} for _ in range(count)]

    def _forks(self, parent: SignalReport) -> list[SignalReport]:
        return list(SignalReport.objects.filter(team=self.team).exclude(id=parent.id))

    def _run(self, signals: list[dict], **options: object) -> None:
        with patch(f"{COMMAND_MODULE_PATH}.fetch_signals_for_report_sync", return_value=signals):
            call_command("backfill_fixed_dismissal_forks", **options)

    def test_forks_one_report_carrying_the_absorbed_signals(self):
        parent = self._dismissed_report("already_fixed")

        self._run(self._signals(3, age=timedelta(minutes=5)))

        forks = self._forks(parent)
        assert len(forks) == 1
        fork = forks[0]
        assert fork.status == SignalReport.Status.POTENTIAL
        assert (fork.title, fork.summary) == (parent.title, parent.summary)
        assert fork.signal_count == 3
        assert fork.total_weight == 1.5
        link = SignalReportArtefact.objects.get(report=fork, type=SignalReportArtefact.ArtefactType.RELATED_TO)
        assert RelatedTo.model_validate_json(link.content) == RelatedTo(report_id=str(parent.id))
        parent.refresh_from_db()
        assert parent.status == SignalReport.Status.SUPPRESSED

    def test_rerunning_does_not_fork_twice(self):
        parent = self._dismissed_report("already_fixed")
        signals = self._signals(3, age=timedelta(minutes=5))

        self._run(signals)
        self._run(signals)

        assert len(self._forks(parent)) == 1

    def test_skips_a_dismissal_that_absorbed_nothing(self):
        # Signals older than the dismissal are the evidence the dismissal was answering, not a
        # recurrence, so they must not fork a report.
        parent = self._dismissed_report("already_fixed")

        self._run(self._signals(3, age=DISMISSED_AGE * 2))

        assert self._forks(parent) == []

    def test_skips_a_dismissal_that_states_a_preference(self):
        parent = self._dismissed_report("wontfix_intentional")

        self._run(self._signals(3, age=timedelta(minutes=5)))

        assert self._forks(parent) == []

    def test_dry_run_writes_nothing(self):
        parent = self._dismissed_report("already_fixed")

        self._run(self._signals(3, age=timedelta(minutes=5)), dry_run=True)

        assert self._forks(parent) == []
