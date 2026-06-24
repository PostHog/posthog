import tempfile
from pathlib import Path

from posthog.test.base import BaseTest

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.persistence import (
    finalize_review_report,
    persist_findings,
    persist_verdicts,
    upsert_review_report,
)


def _pr_metadata(pr_number: int = 123) -> PRMetadata:
    return PRMetadata(
        number=pr_number,
        title="t",
        state="open",
        draft=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        author="a",
        base_branch="main",
        head_branch="feat",
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


def _write_issues(review_dir: Path, issues: list[Issue]) -> None:
    (review_dir / "issues_found.json").write_text(IssueCombination(issues=issues).model_dump_json())


def _write_validation(review_dir: Path, issue_id: str, validation: IssueValidation) -> None:
    pass_id, chunk_id, issue_number = issue_id.split("-")
    summaries = review_dir / f"pass{pass_id}_results" / "validation" / "summaries"
    summaries.mkdir(parents=True, exist_ok=True)
    (summaries / f"chunk-{chunk_id}-issue-{issue_number}-validation-summary.json").write_text(
        validation.model_dump_json()
    )


class TestUpsertReviewReport(BaseTest):
    def test_upsert_is_idempotent_and_each_finalized_turn_bumps_run_count(self) -> None:
        # The living-report premise: re-running a PR must reuse one report (not spawn a second) and
        # count each finalized turn. A broken idempotency key or a finalize that forgets to bump
        # would break the loop-y design.
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            (review_dir / "review_report.md").write_text("# report")

            report_id_1 = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata()
            )
            finalize_review_report(team_id=self.team.id, report_id=report_id_1, review_dir=review_dir)
            report_id_2 = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata()
            )
            finalize_review_report(team_id=self.team.id, report_id=report_id_2, review_dir=review_dir)

        assert report_id_1 == report_id_2
        reports = ReviewReport.objects.for_team(self.team.id).filter(repository="o/r", pr_number=123)
        assert reports.count() == 1
        report = reports.get()
        assert report.run_count == 2
        assert report.report_markdown == "# report"
        assert report.status == ReviewReport.Status.IDLE


class TestPersistResults(BaseTest):
    def test_finding_and_verdict_share_key_and_map_fields(self) -> None:
        # The mapping + join is the whole point of this layer: Issue.issue → finding.body (not
        # suggestion), the typo'd is_directy_* → is_directly_*, and the verdict reaching the finding
        # by a shared issue_key (so latest-wins can pair them). Catches a field swap or a key drift.
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            issue = Issue(
                id="1-2-3",
                title="Off-by-one",
                file="a.py",
                lines=[LineRange(start=10)],
                issue="loop runs one short",
                suggestion="use <=",
                priority=IssuePriority.MUST_FIX,
                source_lens="Logic & Correctness",
                is_directy_related_to_changes=True,
            )
            _write_issues(review_dir, [issue])
            _write_validation(
                review_dir, "1-2-3", IssueValidation(is_valid=True, argumentation="real bug", category="bug")
            )

            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata()
            )
            assert persist_findings(team_id=self.team.id, report_id=report_id, review_dir=review_dir) == 1
            assert persist_verdicts(team_id=self.team.id, report_id=report_id, review_dir=review_dir) == 1

        finding_row = ReviewReportArtefact.objects.for_team(self.team.id).get(
            report_id=report_id, type=ReviewReportArtefact.ArtefactType.ISSUE_FINDING
        )
        verdict_row = ReviewReportArtefact.objects.for_team(self.team.id).get(
            report_id=report_id, type=ReviewReportArtefact.ArtefactType.VALIDATION_VERDICT
        )
        finding = parse_artefact_content(finding_row.type, finding_row.content)
        verdict = parse_artefact_content(verdict_row.type, verdict_row.content)
        assert isinstance(finding, ReviewIssueFinding)
        assert isinstance(verdict, ValidationVerdict)
        assert finding.body == "loop runs one short"
        assert finding.suggestion == "use <="
        assert finding.is_directly_related_to_changes is True
        assert finding.priority == IssuePriority.MUST_FIX
        assert verdict.issue_key == finding.issue_key
        assert verdict.is_valid is True
        assert verdict.category == "bug"
        # System attribution: aggregated across many sandbox tasks, so neither column is set.
        assert finding_row.created_by_id is None
        assert finding_row.task_id is None

    def test_persist_findings_skips_unpersistable_and_keeps_the_rest(self) -> None:
        # A single malformed LLM finding (empty body) must not abort the whole batch.
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            good = Issue(
                id="1-1-1",
                title="ok",
                file="a.py",
                lines=[LineRange(start=1)],
                issue="real description",
                suggestion="s",
                priority=IssuePriority.CONSIDER,
            )
            bad = Issue(
                id="1-1-2",
                title="bad",
                file="b.py",
                lines=[],
                issue="   ",
                suggestion="s",
                priority=IssuePriority.CONSIDER,
            )
            _write_issues(review_dir, [good, bad])

            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata()
            )
            assert persist_findings(team_id=self.team.id, report_id=report_id, review_dir=review_dir) == 1

        rows = ReviewReportArtefact.objects.for_team(self.team.id).filter(
            report_id=report_id, type=ReviewReportArtefact.ArtefactType.ISSUE_FINDING
        )
        assert rows.count() == 1
