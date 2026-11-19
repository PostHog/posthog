from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.clickhouse.client.connection import ClickHouseUser

from products.signals.backend.artefact_schemas import ReportLink
from products.signals.backend.auto_start import _evaluate_link_gates
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.issue_dependencies import (
    IssueMatch,
    IssueRef,
    ReportIssue,
    _issue_matches,
    report_issues,
    reports_waiting_on_issues_of,
    resolve_issue_dependencies,
    unresolved_dependency_skip,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.test.test_signal_queries import _SignalEmbeddingsTestBase
from products.signals.backend.typed_report_links import outgoing_links

MODULE = "products.signals.backend.issue_dependencies"
DEPENDENT_ISSUE = IssueRef(repository="acme/app", number=2)
DEPENDENCY_ISSUE = IssueRef(repository="acme/app", number=1)


class TestIssueDependencies(BaseTest):
    def _report(self, status: str = SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=status, title="t", summary="s", signal_count=1, total_weight=1.0
        )

    def _resolve(
        self, report: SignalReport, *, depends_on: tuple[IssueRef, ...], matches: dict[IssueRef, IssueMatch]
    ) -> tuple[IssueRef, ...]:
        with (
            patch(
                f"{MODULE}.report_issues",
                return_value=[ReportIssue(ref=DEPENDENT_ISSUE, depends_on=depends_on)],
            ),
            patch(f"{MODULE}._issue_matches", return_value=matches),
        ):
            return resolve_issue_dependencies(team_id=self.team.id, report_id=str(report.id))

    def _targets(self, report: SignalReport) -> list[str]:
        return [
            edge.target_id
            for edge in outgoing_links(team_id=self.team.id, report_id=report.id, kinds=(ReportLinkKind.DEPENDS_ON,))
        ]

    def test_dependency_report_without_pull_request_gets_a_link_that_holds_autostart(self) -> None:
        dependent, dependency = self._report(), self._report()
        matches = {DEPENDENCY_ISSUE: IssueMatch(report_ids=(str(dependency.id),), closed=False)}

        assert self._resolve(dependent, depends_on=(DEPENDENCY_ISSUE,), matches=matches) == ()
        assert self._resolve(dependent, depends_on=(DEPENDENCY_ISSUE,), matches=matches) == ()

        assert self._targets(dependent) == [str(dependency.id)]
        skip = _evaluate_link_gates(self.team.id, str(dependent.id))
        assert skip is not None
        assert skip.skip_reason == "blocked_by_dependency"
        assert skip.linked_report_id == str(dependency.id)

    def test_closed_dependency_issue_counts_as_met(self) -> None:
        dependent, dependency = self._report(), self._report()
        matches = {DEPENDENCY_ISSUE: IssueMatch(report_ids=(str(dependency.id),), closed=True)}

        assert self._resolve(dependent, depends_on=(DEPENDENCY_ISSUE,), matches=matches) == ()
        assert self._targets(dependent) == []

    def test_missing_dependency_holds_until_its_report_appears(self) -> None:
        dependent = self._report()
        unrelated = self._report()

        unresolved = self._resolve(dependent, depends_on=(DEPENDENCY_ISSUE,), matches={})
        assert unresolved == (DEPENDENCY_ISSUE,)
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(dependent.id),
            content=unresolved_dependency_skip(unresolved),
            attribution=ArtefactAttribution.system(),
        )
        # A hold on `acme/app#12` must not read as a hold on `acme/app#1`.
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(unrelated.id),
            content=unresolved_dependency_skip([IssueRef(repository="acme/app", number=12)]),
            attribution=ArtefactAttribution.system(),
        )

        dependency = self._report()
        with patch(f"{MODULE}.report_issues", return_value=[ReportIssue(ref=DEPENDENCY_ISSUE, depends_on=())]):
            waiting = reports_waiting_on_issues_of(team_id=self.team.id, report_id=str(dependency.id))
        assert waiting == [str(dependent.id)]

        matches = {DEPENDENCY_ISSUE: IssueMatch(report_ids=(str(dependency.id),), closed=False)}
        assert self._resolve(dependent, depends_on=(DEPENDENCY_ISSUE,), matches=matches) == ()
        assert self._targets(dependent) == [str(dependency.id)]

    def test_dependency_on_a_duplicate_links_to_the_canonical_report(self) -> None:
        dependent, canonical, duplicate = self._report(), self._report(), self._report()
        suppressed = self._report(SignalReport.Status.SUPPRESSED)
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(duplicate.id),
            content=ReportLink(kind=ReportLinkKind.DUPLICATE_OF, report_id=str(canonical.id)),
            attribution=ArtefactAttribution.system(),
        )
        matches = {
            DEPENDENCY_ISSUE: IssueMatch(report_ids=(str(suppressed.id), str(duplicate.id)), closed=False),
        }

        assert self._resolve(dependent, depends_on=(DEPENDENCY_ISSUE,), matches=matches) == ()
        assert self._targets(dependent) == [str(canonical.id)]

    def test_removed_dependency_line_keeps_the_link_and_notes_it_once(self) -> None:
        dependent, dependency = self._report(), self._report()
        matches = {DEPENDENCY_ISSUE: IssueMatch(report_ids=(str(dependency.id),), closed=False)}
        self._resolve(dependent, depends_on=(DEPENDENCY_ISSUE,), matches=matches)

        self._resolve(dependent, depends_on=(), matches={})
        self._resolve(dependent, depends_on=(), matches={})

        assert self._targets(dependent) == [str(dependency.id)]
        notes = SignalReportArtefact.objects.filter(
            team_id=self.team.id, report_id=dependent.id, type=SignalReportArtefact.ArtefactType.NOTE
        )
        assert notes.count() == 1
        assert "acme/app#1" in notes.get().content


class TestIssueDependencyQueries(_SignalEmbeddingsTestBase):
    def test_reads_current_refs_and_matches_issues_by_url(self) -> None:
        dependent_url = "https://github.com/Acme/App/issues/2"
        self._emit_version(
            document_id="dep-v1",
            report_id="r-dependent",
            source_product="github",
            source_type="issue",
            source_id="issue-2",
            inserted_at=self.base,
            extra={"html_url": dependent_url, "depends_on_issues": [{"repository": "acme/app", "number": 9}]},
        )
        # The edited body emits a new signal, and only that one says what the issue depends on now.
        self._emit_version(
            document_id="dep-v2",
            report_id="r-dependent",
            source_product="github",
            source_type="issue",
            source_id="issue-2",
            inserted_at=self.base + timedelta(minutes=1),
            extra={"html_url": dependent_url, "depends_on_issues": [{"repository": "acme/app", "number": 1}]},
        )
        self._emit_version(
            document_id="target",
            report_id="r-dependency",
            source_product="github",
            source_type="issue",
            source_id="issue-1",
            inserted_at=self.base,
            extra={"html_url": "https://github.com/ACME/app/issues/1", "state": "open"},
        )

        assert report_issues(self.team, "r-dependent", ch_user=ClickHouseUser.DEFAULT) == [
            ReportIssue(ref=DEPENDENT_ISSUE, depends_on=(DEPENDENCY_ISSUE,))
        ]
        missing = IssueRef(repository="acme/app", number=3)
        assert _issue_matches(self.team, [DEPENDENCY_ISSUE, missing], ch_user=ClickHouseUser.DEFAULT) == {
            DEPENDENCY_ISSUE: IssueMatch(report_ids=("r-dependency",), closed=False)
        }
