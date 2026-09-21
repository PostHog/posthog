from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import Dismissal, ReportLink
from products.signals.backend.enums import ReportLinkKind
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
        return [
            {"timestamp": timezone.now() - age, "weight": 0.5, "source_product": "error_tracking"} for _ in range(count)
        ]

    def _forks(self, parent: SignalReport) -> list[SignalReport]:
        return list(SignalReport.objects.filter(team=self.team).exclude(id=parent.id))

    def _run(self, signals: list[dict], **options: object) -> None:
        with patch(f"{COMMAND_MODULE_PATH}.fetch_signals_for_report_sync", return_value=signals):
            call_command("backfill_fixed_dismissal_forks", **options)

    def test_fork_does_not_count_signals_stored_on_the_parent(self):
        parent = self._dismissed_report("already_fixed")

        self._run(self._signals(3, age=timedelta(minutes=5)))

        forks = self._forks(parent)
        assert len(forks) == 1
        fork = forks[0]
        assert fork.status == SignalReport.Status.POTENTIAL
        assert (fork.title, fork.summary) == (parent.title, parent.summary)
        assert fork.signal_count == 0
        assert fork.total_weight == 0
        link = SignalReportArtefact.objects.get(report=fork, type=SignalReportArtefact.ArtefactType.REPORT_LINK)
        assert ReportLink.model_validate_json(link.content) == ReportLink(
            kind=ReportLinkKind.RECURRENCE_OF, report_id=str(parent.id)
        )
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

    def test_accepts_string_and_naive_timestamps(self):
        parent = self._dismissed_report("already_fixed")
        signals = self._signals(2, age=timedelta(minutes=5))
        signals[0]["timestamp"] = signals[0]["timestamp"].isoformat()
        signals[1]["timestamp"] = signals[1]["timestamp"].replace(tzinfo=None)

        self._run(signals)

        assert len(self._forks(parent)) == 1

    def test_billing_uses_the_first_recurrence_source(self):
        parent = self._dismissed_report("already_fixed")
        signals = self._signals(2, age=timedelta(minutes=5))
        signals[1]["timestamp"] -= timedelta(minutes=1)
        signals[1]["source_product"] = "health_checks"

        self._run(signals)

        assert self._forks(parent)[0].billing_exempt_reason == SignalReport.BillingExemptReason.POSTHOG_HEALTH_CHECK

    def test_billable_recurrence_does_not_inherit_parent_exemption(self):
        parent = self._dismissed_report("already_fixed")
        parent.billing_exempt_reason = SignalReport.BillingExemptReason.POSTHOG_HEALTH_CHECK
        parent.save(update_fields=["billing_exempt_reason"])

        self._run(self._signals(1, age=timedelta(minutes=5)))

        assert self._forks(parent)[0].billing_exempt_reason is None

    def test_rechecks_for_a_successor_under_the_parent_lock(self):
        parent = self._dismissed_report("already_fixed")

        def concurrent_recurrence(team, report_id):
            successor = SignalReport.objects.create(team=self.team)
            SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=str(successor.id),
                content=ReportLink(kind=ReportLinkKind.RECURRENCE_OF, report_id=str(parent.id)),
                attribution=ArtefactAttribution.system(),
            )
            return self._signals(1, age=timedelta(minutes=5))

        with patch(f"{COMMAND_MODULE_PATH}.fetch_signals_for_report_sync", side_effect=concurrent_recurrence):
            call_command("backfill_fixed_dismissal_forks")

        assert len(self._forks(parent)) == 1

    def test_rechecks_parent_state_after_fetching_signals(self):
        parent = self._dismissed_report("already_fixed")

        def concurrent_restore(team, report_id):
            SignalReport.objects.filter(id=parent.id).update(status=SignalReport.Status.READY)
            return self._signals(1, age=timedelta(minutes=5))

        with patch(f"{COMMAND_MODULE_PATH}.fetch_signals_for_report_sync", side_effect=concurrent_restore):
            call_command("backfill_fixed_dismissal_forks")

        assert self._forks(parent) == []

    def test_team_cache_queries_each_team_once(self):
        self._dismissed_report("already_fixed")
        self._dismissed_report("already_fixed")

        with patch(f"{COMMAND_MODULE_PATH}.Team.objects.get", wraps=type(self.team).objects.get) as get_team:
            self._run(self._signals(1, age=timedelta(minutes=5)))

        get_team.assert_called_once_with(pk=self.team.id)
