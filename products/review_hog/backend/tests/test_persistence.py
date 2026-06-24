import tempfile
from pathlib import Path

from posthog.test.base import BaseTest

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.persistence import (
    finalize_review_report,
    persist_commit_snapshot,
    persist_findings,
    persist_verdicts,
    upsert_review_report,
)
from products.signals.backend.artefact_schemas import Commit


def _pr_metadata(pr_number: int = 123, head_sha: str | None = None) -> PRMetadata:
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
        head_sha=head_sha,
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

    def test_colliding_findings_persist_distinctly_and_pair_to_own_verdict(self) -> None:
        # Two genuinely distinct issues from the same lens on the same start line survive dedup with
        # different ids. They must NOT collapse to one issue_key (which would shadow a finding) and
        # each must pair to its OWN verdict (not the other's ruling).
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            a = Issue(
                id="1-2-1",
                title="A",
                file="x.py",
                lines=[LineRange(start=5)],
                issue="problem A",
                suggestion="fix A",
                priority=IssuePriority.MUST_FIX,
                source_lens="Logic & Correctness",
            )
            b = Issue(
                id="1-2-2",
                title="B",
                file="x.py",
                lines=[LineRange(start=5)],
                issue="problem B",
                suggestion="fix B",
                priority=IssuePriority.SHOULD_FIX,
                source_lens="Logic & Correctness",
            )
            _write_issues(review_dir, [a, b])
            _write_validation(review_dir, "1-2-1", IssueValidation(is_valid=True, argumentation="A is real"))
            _write_validation(review_dir, "1-2-2", IssueValidation(is_valid=False, argumentation="B dismissed"))

            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata()
            )
            assert persist_findings(team_id=self.team.id, report_id=report_id, review_dir=review_dir) == 2
            assert persist_verdicts(team_id=self.team.id, report_id=report_id, review_dir=review_dir) == 2

        finding_keys = {
            parse_artefact_content(r.type, r.content).issue_key
            for r in ReviewReportArtefact.objects.for_team(self.team.id).filter(
                report_id=report_id, type=ReviewReportArtefact.ArtefactType.ISSUE_FINDING
            )
        }
        assert len(finding_keys) == 2
        verdicts = {
            v.issue_key: v
            for v in (
                parse_artefact_content(r.type, r.content)
                for r in ReviewReportArtefact.objects.for_team(self.team.id).filter(
                    report_id=report_id, type=ReviewReportArtefact.ArtefactType.VALIDATION_VERDICT
                )
            )
        }
        assert set(verdicts) == finding_keys
        # A's verdict (valid) and B's verdict (invalid) attach to A's and B's finding respectively.
        a_key = next(k for k in verdicts if k.endswith(":1-2-1"))
        b_key = next(k for k in verdicts if k.endswith(":1-2-2"))
        assert verdicts[a_key].is_valid is True
        assert verdicts[b_key].is_valid is False

    def test_verdict_not_written_for_issue_whose_finding_was_skipped(self) -> None:
        # An issue that fails durable finding validation must not leave behind an orphan verdict, even
        # when it has a validation summary on disk (the finding schema is stricter than the verdict's).
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
                source_lens="Logic & Correctness",
            )
            bad = Issue(
                id="1-1-2",
                title="bad",
                file="b.py",
                lines=[LineRange(start=1)],
                issue="   ",
                suggestion="s",
                priority=IssuePriority.CONSIDER,
                source_lens="Logic & Correctness",
            )
            _write_issues(review_dir, [good, bad])
            _write_validation(review_dir, "1-1-1", IssueValidation(is_valid=True, argumentation="ok"))
            _write_validation(review_dir, "1-1-2", IssueValidation(is_valid=True, argumentation="orphan ruling"))

            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata()
            )
            assert persist_findings(team_id=self.team.id, report_id=report_id, review_dir=review_dir) == 1
            assert persist_verdicts(team_id=self.team.id, report_id=report_id, review_dir=review_dir) == 1

        verdicts = [
            parse_artefact_content(r.type, r.content)
            for r in ReviewReportArtefact.objects.for_team(self.team.id).filter(
                report_id=report_id, type=ReviewReportArtefact.ArtefactType.VALIDATION_VERDICT
            )
        ]
        assert len(verdicts) == 1
        assert verdicts[0].issue_key.endswith(":1-1-1")

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


class TestPersistCommitSnapshot(BaseTest):
    def _commits(self, report_id: str):
        return ReviewReportArtefact.objects.for_team(self.team.id).filter(
            report_id=report_id, type=ReviewReportArtefact.ArtefactType.COMMIT
        )

    def test_snapshot_stores_the_diff_at_head_sha_and_advances_both_watermarks(self) -> None:
        # The point-in-time guarantee: the reviewed diff is captured against the exact head_sha and
        # the watermark advances so a later turn knows what was reviewed. A dropped diff, a wrong
        # sha, or a forgotten watermark bump would all surface here.
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            (review_dir / "pr_diff.patch").write_text("=== a.py [modified] ===\n@@ -1 +1 @@\n-old\n+new")
            comments = [PRComment(id=11, path="a.py", body="hi", diff_hunk="", user="u", created_at="t")]

            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha-aaa")
            )
            appended = persist_commit_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                repository="o/r",
                pr_metadata=_pr_metadata(head_sha="sha-aaa"),
                pr_comments=comments,
                review_dir=review_dir,
            )

        assert appended is True
        row = self._commits(report_id).get()
        commit = parse_artefact_content(row.type, row.content)
        assert isinstance(commit, Commit)
        assert commit.commit_sha == "sha-aaa"
        assert commit.diff == "=== a.py [modified] ===\n@@ -1 +1 @@\n-old\n+new"
        # System attribution: the orchestrator's fetch produced it, not a sandbox task.
        assert row.created_by_id is None
        assert row.task_id is None
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.head_sha == "sha-aaa"
        assert report.last_seen_comment_id == 11

    def test_snapshot_is_idempotent_when_head_sha_is_unchanged(self) -> None:
        # A re-run with no new commits must not duplicate the snapshot — this is exactly the loop's
        # no-op turn. Without the watermark guard the report would accrete identical snapshots forever.
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            (review_dir / "pr_diff.patch").write_text("@@ -1 +1 @@")
            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha-aaa")
            )
            first = persist_commit_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                repository="o/r",
                pr_metadata=_pr_metadata(head_sha="sha-aaa"),
                pr_comments=[],
                review_dir=review_dir,
            )
            second = persist_commit_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                repository="o/r",
                pr_metadata=_pr_metadata(head_sha="sha-aaa"),
                pr_comments=[],
                review_dir=review_dir,
            )

        assert first is True
        assert second is False
        assert self._commits(report_id).count() == 1

    def test_new_head_sha_appends_a_second_snapshot(self) -> None:
        # When the PR head actually moves, the new turn must append its own snapshot (never mutate
        # the prior one) so the per-turn history survives later force-pushes. Too-aggressive guarding
        # would silently lose the later turn's diff.
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            (review_dir / "pr_diff.patch").write_text("turn-1 diff")
            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha-aaa")
            )
            persist_commit_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                repository="o/r",
                pr_metadata=_pr_metadata(head_sha="sha-aaa"),
                pr_comments=[],
                review_dir=review_dir,
            )
            (review_dir / "pr_diff.patch").write_text("turn-2 diff")
            appended = persist_commit_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                repository="o/r",
                pr_metadata=_pr_metadata(head_sha="sha-bbb"),
                pr_comments=[],
                review_dir=review_dir,
            )

        assert appended is True
        diffs = {parse_artefact_content(r.type, r.content).diff for r in self._commits(report_id)}
        assert diffs == {"turn-1 diff", "turn-2 diff"}
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.head_sha == "sha-bbb"

    def test_snapshot_skipped_when_head_sha_missing(self) -> None:
        # A stale pre-snapshot cache leaves head_sha unset; the snapshot must skip cleanly rather
        # than build a Commit with a blank sha (which the schema rejects).
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha=None)
            )
            appended = persist_commit_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                repository="o/r",
                pr_metadata=_pr_metadata(head_sha=None),
                pr_comments=[],
                review_dir=review_dir,
            )

        assert appended is False
        assert self._commits(report_id).count() == 0
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).head_sha is None

    def test_snapshot_deferred_and_recoverable_when_patch_file_missing(self) -> None:
        # If the raw patch wasn't captured (partial fetch / pre-snapshot scratch dir), the snapshot
        # must DEFER — append nothing and NOT advance head_sha — so the un-captured diff stays
        # recoverable on a later fresh run. Advancing past it would lock the diff out forever.
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha-aaa")
            )
            appended = persist_commit_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                repository="o/r",
                pr_metadata=_pr_metadata(head_sha="sha-aaa"),
                pr_comments=[],
                review_dir=review_dir,
            )

        assert appended is False
        assert self._commits(report_id).count() == 0
        # head_sha not advanced: a later run (with the diff captured) can still snapshot this commit.
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).head_sha is None

    def test_snapshot_records_empty_diff_when_no_reviewable_files(self) -> None:
        # An empty pr_diff.patch is a legitimate "everything filtered out" turn (not a missing file):
        # record the commit with diff=None and advance the watermark, rather than defer forever.
        with tempfile.TemporaryDirectory() as d:
            review_dir = Path(d)
            (review_dir / "pr_diff.patch").write_text("")
            report_id = upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha-aaa")
            )
            appended = persist_commit_snapshot(
                team_id=self.team.id,
                report_id=report_id,
                repository="o/r",
                pr_metadata=_pr_metadata(head_sha="sha-aaa"),
                pr_comments=[],
                review_dir=review_dir,
            )

        assert appended is True
        commit = parse_artefact_content(*self._commits(report_id).values_list("type", "content").get())
        assert commit.diff is None
        assert commit.commit_sha == "sha-aaa"
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).head_sha == "sha-aaa"
