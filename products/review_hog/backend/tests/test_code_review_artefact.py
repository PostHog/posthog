import uuid

from posthog.test.base import BaseTest

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.persistence import persist_findings, persist_verdicts, upsert_review_report
from products.review_hog.backend.temporal.activities import AppendCodeReviewArtefactInput, _append_code_review_artefact
from products.signals.backend.artefact_schemas import CodeReview, parse_artefact_content
from products.signals.backend.models import SignalReport, SignalReportArtefact

_PR_URL = "https://github.com/o/r/pull/7"
_REVIEW_URL = f"{_PR_URL}#pullrequestreview-1"


def _pr_metadata() -> PRMetadata:
    return PRMetadata(
        number=7,
        title="t",
        state="open",
        draft=False,
        created_at="",
        updated_at="",
        author="octocat",
        base_branch="main",
        head_branch="feat",
        head_sha="sha1",
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


def _issue(issue_id: str, priority: IssuePriority) -> Issue:
    return Issue(
        id=issue_id,
        title="t",
        file="a.py",
        lines=[LineRange(start=10)],
        issue="problem",
        suggestion="fix",
        priority=priority,
        source_perspective="Logic & Correctness",
    )


class TestAppendCodeReviewArtefact(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.signal_report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.IN_PROGRESS, signal_count=1, total_weight=1.0
        )

    def _review_report(self) -> str:
        report_id = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url=_PR_URL, pr_metadata=_pr_metadata()
        )
        # The head watermark is normally advanced by the fetch's commit snapshot.
        ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(head_sha="sha1")
        return report_id

    def _input(self, *, signal_report_id: str, review_report_id: str) -> AppendCodeReviewArtefactInput:
        return AppendCodeReviewArtefactInput(
            team_id=self.team.id,
            signal_report_id=signal_report_id,
            review_report_id=review_report_id,
            run_index=1,
            outcome="published",
            review_url=_REVIEW_URL,
        )

    def test_appends_a_parsed_receipt_with_effective_priority_counts(self) -> None:
        # End-to-end through the real rows and the signals write funnel: the receipt must count only
        # validator-passed findings, at the validator's adjusted priority (validator-wins), and carry
        # the drill-down pointers. A drift here misreports every review on the Inbox timeline.
        report_id = self._review_report()
        issues = [
            _issue("1-1-1", IssuePriority.MUST_FIX),  # valid, kept at must_fix
            _issue("1-1-2", IssuePriority.SHOULD_FIX),  # valid, downgraded to consider
            _issue("1-1-3", IssuePriority.MUST_FIX),  # validator-rejected → excluded
        ]
        persist_findings(team_id=self.team.id, report_id=report_id, issues=issues, run_index=1)
        persist_verdicts(
            team_id=self.team.id,
            report_id=report_id,
            issues=issues,
            run_index=1,
            validations={
                "1-1-1": IssueValidation(is_valid=True, argumentation="real", category="bug"),
                "1-1-2": IssueValidation(
                    is_valid=True, argumentation="minor", category="bug", adjusted_priority=IssuePriority.CONSIDER
                ),
                "1-1-3": IssueValidation(is_valid=False, argumentation="not real", category="bug"),
            },
        )

        _append_code_review_artefact(
            self._input(signal_report_id=str(self.signal_report.id), review_report_id=report_id)
        )

        row = SignalReportArtefact.objects.get(report=self.signal_report, type="code_review")
        content = parse_artefact_content("code_review", row.content)
        assert isinstance(content, CodeReview)
        assert (content.counts.must_fix, content.counts.should_fix, content.counts.consider) == (1, 0, 1)
        assert content.review_report_id == report_id
        assert content.repository == "o/r"
        assert content.head_sha == "sha1"
        assert content.head_branch == "feat"
        assert content.pr_number == 7
        assert content.pr_url == _PR_URL
        assert content.review_url == _REVIEW_URL
        assert content.outcome == "published"
        # System-attributed, like every pipeline-produced artefact.
        assert row.created_by_id is None
        assert row.task_id is None

    def test_missing_signal_report_is_tolerated(self) -> None:
        # The signals report can be deleted/reingested mid-run; the receipt append must be a no-op,
        # never an error that fails the review over its own bookkeeping.
        report_id = self._review_report()

        _append_code_review_artefact(self._input(signal_report_id=str(uuid.uuid4()), review_report_id=report_id))

        assert not SignalReportArtefact.objects.filter(type="code_review").exists()
