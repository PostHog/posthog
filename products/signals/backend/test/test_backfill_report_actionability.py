import json

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.signals.backend.models import SignalReport, SignalReportArtefact


class TestBackfillReportActionability(BaseTest):
    def _report(self, *, actionability: str | None) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="t",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )
        if actionability is not None:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                content=json.dumps(
                    {"explanation": "x", "actionability": actionability, "already_addressed": True},
                ),
            )
        return report

    def _cached(self, report: SignalReport) -> tuple[str | None, bool | None]:
        row = SignalReport.objects.filter(id=report.id).values("latest_actionability", "latest_already_addressed")[0]
        return row["latest_actionability"], row["latest_already_addressed"]

    def test_repairs_a_report_whose_cache_disagrees_with_its_artefacts(self):
        drifted = self._report(actionability="requires_human_input")
        never_judged = self._report(actionability=None)
        SignalReport.objects.filter(id=drifted.id).update(
            latest_actionability="not_actionable", latest_already_addressed=False
        )
        SignalReport.objects.filter(id=never_judged.id).update(latest_actionability="immediately_actionable")

        call_command("backfill_report_actionability", "--team-id", str(self.team.id), "--batch-size", "1")

        assert self._cached(drifted) == ("requires_human_input", True)
        assert self._cached(never_judged) == (None, None)
