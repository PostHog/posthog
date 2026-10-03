from posthog.test.base import BaseTest

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_page_source import report_artefact_texts


class TestReportArtefactTexts(BaseTest):
    def test_returns_the_asked_types_and_who_wrote_each(self) -> None:
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
        )
        for content, created_by in [("By the agent.", None), ("By a person.", self.user)]:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.NOTE,
                content=content,
                created_by=created_by,
            )
        SignalReportArtefact.objects.create(
            team=self.team, report=report, type=SignalReportArtefact.ArtefactType.REPO_SELECTION, content="{}"
        )

        texts = report_artefact_texts(team=self.team, report_id=str(report.id), types=["note"])

        assert sorted((text.content, text.written_by_person) for text in texts) == [
            ("By a person.", True),
            ("By the agent.", False),
        ]
