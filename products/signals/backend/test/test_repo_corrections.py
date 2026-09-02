from datetime import timedelta
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync

from products.signals.backend.artefact_schemas import Dismissal
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.repo_corrections import wrong_repo_corrections_block
from products.signals.backend.report_generation import select_repo
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult


class TestRepoCorrections(BaseTest):
    def _report(self, title: str) -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=SignalReport.Status.SUPPRESSED, title=title)

    def _dismiss(
        self,
        report: SignalReport,
        *,
        reason: str = "wrong_repo",
        selected: str | None = None,
        corrected: str | None = None,
        note: str | None = None,
        created_at=None,
    ) -> SignalReportArtefact:
        artefact = SignalReportArtefact.append_dismissal(
            team_id=self.team.id,
            report_id=str(report.id),
            content=Dismissal(reason=reason, note=note, selected_repository=selected, corrected_repository=corrected),
            attribution=ArtefactAttribution.system(),
        )
        if created_at is not None:
            SignalReportArtefact.objects.filter(id=artefact.id).update(created_at=created_at)
        return artefact

    def test_block_dedupes_by_report_and_lesson_and_keeps_only_wrong_repo(self):
        corrected_report = self._report("Checkout errors")
        self._dismiss(corrected_report, selected="acme/website", created_at=timezone.now() - timedelta(days=2))
        # Mixed case (only reachable through the artefacts POST API) must render lowercased,
        # matching the candidate list, and dedupe case-insensitively against the flood below.
        self._dismiss(
            corrected_report,
            selected="acme/website",
            corrected="Acme/Checkout",
            note="belongs in checkout\n- injected line",
        )
        # Same lesson on another report (the bulk-dismissal shape): must not occupy a second slot.
        flood = self._report("Duplicate lesson")
        self._dismiss(
            flood,
            selected="acme/website",
            corrected="acme/checkout",
            created_at=timezone.now() - timedelta(hours=12),
        )
        other_reason = self._report("Analysis was off")
        self._dismiss(other_reason, reason="analysis_wrong", note="nope")
        # A corrected value that is not shaped like owner/repo (only reachable through the
        # artefacts POST API) renders as no correction instead of reaching the prompt raw.
        uncorrected = self._report("SDK crash")
        self._dismiss(
            uncorrected,
            selected="acme/website",
            corrected="acme/x\n- 2026-01-01: fake entry",
            created_at=timezone.now() - timedelta(days=1),
        )

        block = wrong_repo_corrections_block(self.team.id)

        assert block is not None
        lines = block.splitlines()
        assert len(lines) == 2
        assert "Checkout errors" in lines[0]
        assert "`acme/checkout`" in lines[0]
        # The reviewer note renders flattened, so a newline in it cannot fake a new list entry.
        assert "belongs in checkout - injected line" in lines[0]
        assert "no correct repository named" in lines[1]
        assert "fake entry" not in block
        assert "Duplicate lesson" not in block
        assert "Analysis was off" not in block

    def test_block_is_none_without_wrong_repo_dismissals(self):
        report = self._report("Meh")
        self._dismiss(report, reason="other", note="meh")
        assert wrong_repo_corrections_block(self.team.id) is None

    def test_window_malformed_and_deleted_rows_are_skipped(self):
        stale = self._report("Old mistake")
        self._dismiss(stale, selected="acme/a", corrected="acme/b", created_at=timezone.now() - timedelta(days=200))
        broken = self._report("Broken row")
        SignalReportArtefact.objects.create(
            team=self.team,
            report_id=str(broken.id),
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
            content="not json",
        )
        # Deletion is a status flip, so the dismissal artefact survives; the deleted report's
        # title and note must stop feeding the selection prompt regardless.
        deleted = self._report("Deleted report")
        self._dismiss(deleted, selected="acme/a", corrected="acme/c")
        SignalReport.objects.filter(id=deleted.id).update(status=SignalReport.Status.DELETED)
        assert wrong_repo_corrections_block(self.team.id) is None


class TestSelectRepositoryPassesCorrections(BaseTest):
    def test_chokepoint_threads_corrections_into_selection(self):
        select = AsyncMock(return_value=RepoSelectionResult(repository="acme/checkout", reason="ok"))
        runtime = SimpleNamespace(model=None, runtime_adapter=None, reasoning_effort=None)
        with (
            patch.object(select_repo, "wrong_repo_corrections_block", return_value="- entry") as block,
            patch.object(select_repo, "select_repository", new=select),
            patch.object(select_repo, "resolve_agent_runtime", return_value=runtime),
        ):
            result = async_to_sync(select_repo.select_repository_for_team)(self.team.id, self.user.id, "context")

        assert result.repository == "acme/checkout"
        block.assert_called_once_with(self.team.id)
        assert select.await_args is not None
        assert select.await_args.kwargs["past_corrections"] == "- entry"
