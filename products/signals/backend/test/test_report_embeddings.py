from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.models import SignalReport
from products.signals.backend.report_embeddings import render_report_document

EMIT_PATH = "products.signals.backend.receivers.emit_report_embedding"


class TestRenderReportDocument(SimpleTestCase):
    @parameterized.expand(
        [
            ("both", "Checkout errors", "Rate tripled", "Checkout errors\n\nRate tripled"),
            ("title_only", "Checkout errors", None, "Checkout errors"),
            ("summary_only", None, "Rate tripled", "Rate tripled"),
            ("neither", None, None, None),
            ("blank_is_treated_as_absent", "", "   ", None),
            ("whitespace_stripped", "  Checkout errors  ", "\nRate tripled\n", "Checkout errors\n\nRate tripled"),
        ]
    )
    def test_renders_title_and_summary(self, _name, title, summary, expected):
        assert render_report_document(title, summary) == expected


class TestReportEmbeddingReceiver(BaseTest):
    def _create_report(self, **kwargs) -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=SignalReport.Status.POTENTIAL, **kwargs)

    def test_report_created_with_text_is_embedded(self):
        with patch(EMIT_PATH) as emit:
            with self.captureOnCommitCallbacks(execute=True):
                report = self._create_report(title="Checkout errors", summary="Rate tripled")
        assert emit.call_count == 1
        assert emit.call_args.kwargs["team_id"] == self.team.id
        assert emit.call_args.kwargs["report_id"] == str(report.id)
        assert emit.call_args.kwargs["content"] == "Checkout errors\n\nRate tripled"

    def test_textless_report_is_embedded_only_once_research_writes_its_summary(self):
        with patch(EMIT_PATH) as emit:
            with self.captureOnCommitCallbacks(execute=True):
                report = self._create_report()
            assert emit.call_count == 0

            report.transition_to(SignalReport.Status.CANDIDATE)
            report.save(update_fields=["status", "promoted_at", "updated_at"])
            report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=1)
            report.save(update_fields=["status", "last_run_at", "signals_at_run", "run_count", "updated_at"])
            assert emit.call_count == 0

            with self.captureOnCommitCallbacks(execute=True):
                updated = report.transition_to(
                    SignalReport.Status.READY, title="Checkout errors", summary="Rate tripled"
                )
                report.save(update_fields=updated)
        assert emit.call_count == 1
        assert emit.call_args.kwargs["content"] == "Checkout errors\n\nRate tripled"

    def test_re_embedding_reuses_the_report_creation_timestamp(self):
        # Pinning the timestamp is what makes a re-emission replace the report's row rather than land
        # in a second partition next to it — see emit_report_embedding.
        with patch(EMIT_PATH) as emit:
            with self.captureOnCommitCallbacks(execute=True):
                report = self._create_report(title="Checkout errors", summary="Rate tripled")
            with self.captureOnCommitCallbacks(execute=True):
                report.summary = "Rate tripled after the deploy"
                report.save(update_fields=["summary", "updated_at"])
        assert emit.call_count == 2
        assert [call.kwargs["created_at"] for call in emit.call_args_list] == [report.created_at, report.created_at]
        assert emit.call_args_list[1].kwargs["content"] == "Checkout errors\n\nRate tripled after the deploy"

    def test_rewriting_the_same_text_does_not_re_embed(self):
        with self.captureOnCommitCallbacks(execute=True):
            report = self._create_report(title="Checkout errors", summary="Rate tripled")
        with patch(EMIT_PATH) as emit:
            with self.captureOnCommitCallbacks(execute=True):
                report.title = "Checkout errors"
                report.save(update_fields=["title", "updated_at"])
        assert emit.call_count == 0

    def test_status_transition_alone_does_not_re_embed(self):
        with self.captureOnCommitCallbacks(execute=True):
            report = self._create_report(
                status=SignalReport.Status.READY, title="Checkout errors", summary="Rate tripled"
            )
        with patch(EMIT_PATH) as emit:
            with self.captureOnCommitCallbacks(execute=True):
                updated = report.transition_to(SignalReport.Status.SUPPRESSED)
                report.save(update_fields=updated)
        assert emit.call_count == 0
