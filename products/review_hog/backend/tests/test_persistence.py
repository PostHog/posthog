import uuid
from typing import TypeVar

from posthog.test.base import BaseTest

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    ChunkSetArtefact,
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.reviewer.persistence import (
    finalize_review_report,
    load_chunk_set,
    load_perspective_results,
    load_pr_snapshot,
    load_prior_findings,
    load_prior_findings_with_verdicts,
    load_run_issues,
    load_run_validations,
    load_valid_findings,
    persist_chunk_set,
    persist_commit_snapshot,
    persist_findings,
    persist_perspective_results,
    persist_pr_snapshot,
    persist_verdict,
    persist_verdicts,
    upsert_review_report,
)
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import Commit

_ContentT = TypeVar("_ContentT")


def _content_as(model: type[_ContentT], artefact_type: str, content: str) -> _ContentT:
    parsed = parse_artefact_content(artefact_type, content)
    assert isinstance(parsed, model)
    return parsed


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


def _issue(issue_id: str, *, file: str = "a.py", start: int = 10, **kwargs: object) -> Issue:
    defaults: dict = {
        "title": "t",
        "file": file,
        "lines": [LineRange(start=start)],
        "issue": "problem",
        "suggestion": "fix",
        "priority": IssuePriority.MUST_FIX,
        "source_perspective": "Logic & Correctness",
    }
    defaults.update(kwargs)
    return Issue(id=issue_id, **defaults)


class TestUpsertReviewReport(BaseTest):
    def test_upsert_is_idempotent_and_each_finalized_turn_bumps_run_count(self) -> None:
        # The living-report premise: re-running a PR must reuse one report (not spawn a second) and
        # count each finalized turn. A broken idempotency key or a finalize that forgets to bump
        # would break the loop-y design.
        report_id_1 = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata()
        )
        finalize_review_report(
            team_id=self.team.id, report_id=report_id_1, body_markdown="# report", run_index=1, head_sha="sha-1"
        )
        report_id_2 = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata()
        )
        finalize_review_report(
            team_id=self.team.id, report_id=report_id_2, body_markdown="# report", run_index=2, head_sha="sha-2"
        )

        assert report_id_1 == report_id_2
        reports = ReviewReport.objects.for_team(self.team.id).filter(repository="o/r", pr_number=123)
        assert reports.count() == 1
        report = reports.get()
        assert report.run_count == 2
        assert report.report_markdown == "# report"
        assert report.status == ReviewReport.Status.IDLE
        assert report.completed_head_sha == "sha-2"  # what the finished turn reviewed, for read anchoring

    def test_finalize_is_idempotent_within_a_turn(self) -> None:
        # build_body_activity retries on worker crash after its finalize committed: the retry must
        # not double-bump run_count, or run_index != run_count and every latest-turn reader (list
        # counts, publish, prior-findings scoping) points one turn ahead of the real findings.
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())

        finalize_review_report(
            team_id=self.team.id, report_id=report_id, body_markdown="# report", run_index=1, head_sha="sha-1"
        )
        finalize_review_report(
            team_id=self.team.id, report_id=report_id, body_markdown="# report", run_index=1, head_sha="sha-1"
        )

        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).run_count == 1

    def test_branch_target_upserts_by_head_branch_and_upgrades_to_pr(self) -> None:
        # A PR-less branch target keys by head_branch (pr_number NULL); the first fetch that finds a
        # PR for the branch must upgrade the SAME row (backfilling number + url) so the stored review
        # and its watermarks carry into the publishable turn instead of splitting across two reports.
        branch_id = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="", pr_metadata=_pr_metadata(pr_number=0)
        )
        assert (
            upsert_review_report(
                team_id=self.team.id, repository="o/r", pr_url="", pr_metadata=_pr_metadata(pr_number=0)
            )
            == branch_id
        )
        row = ReviewReport.objects.for_team(self.team.id).get(id=branch_id)
        assert row.pr_number is None
        assert row.head_branch == "feat"

        upgraded = upsert_review_report(
            team_id=self.team.id,
            repository="o/r",
            pr_url="https://github.com/o/r/pull/123",
            pr_metadata=_pr_metadata(),
        )
        assert upgraded == branch_id
        # Re-fetch instead of refresh_from_db: the `pr_number is None` assert above narrows the
        # attribute for mypy, and a refresh does not reset that narrowing.
        refreshed = ReviewReport.objects.for_team(self.team.id).get(id=branch_id)
        assert refreshed.pr_number == 123
        assert refreshed.pr_url == "https://github.com/o/r/pull/123"
        assert ReviewReport.objects.for_team(self.team.id).filter(repository="o/r").count() == 1

    def test_provenance_is_stamped_on_create_and_never_overwritten(self) -> None:
        # The signals link is the durable provenance (the artefact on the signals side is deletable):
        # an inbox create stamps it, and a later label re-trigger of the same PR must not erase it.
        signal_report_id = str(uuid.uuid4())
        report_id = upsert_review_report(
            team_id=self.team.id,
            repository="o/r",
            pr_url="u",
            pr_metadata=_pr_metadata(),
            signal_report_id=signal_report_id,
            trigger_source="inbox",
        )
        upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(), trigger_source="label"
        )

        row = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert str(row.signal_report_id) == signal_report_id
        assert row.trigger_source == "inbox"

    def test_provenance_backfills_only_when_missing(self) -> None:
        # The reverse overlap: a label-created report later re-triggered by the inbox flow gains the
        # missing signal link but keeps its creating trigger.
        report_id = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(), trigger_source="label"
        )
        signal_report_id = str(uuid.uuid4())
        upsert_review_report(
            team_id=self.team.id,
            repository="o/r",
            pr_url="u",
            pr_metadata=_pr_metadata(),
            signal_report_id=signal_report_id,
            trigger_source="inbox",
        )

        row = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert str(row.signal_report_id) == signal_report_id
        assert row.trigger_source == "label"


class TestPersistResults(BaseTest):
    def test_finding_and_verdict_share_key_and_map_fields(self) -> None:
        # The mapping + join is the whole point of this layer: Issue.issue → finding.body (not
        # suggestion), the typo'd is_directy_* → is_directly_*, and the verdict reaching the finding
        # by a shared issue_key (so latest-wins can pair them). Catches a field swap or a key drift.
        issue = _issue(
            "1-2-3",
            title="Off-by-one",
            file="a.py",
            issue="loop runs one short",
            suggestion="use <=",
            is_directly_related_to_changes=True,
        )
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        assert persist_findings(team_id=self.team.id, report_id=report_id, issues=[issue], run_index=1) == ["1-2-3"]
        assert (
            persist_verdicts(
                team_id=self.team.id,
                report_id=report_id,
                issues=[issue],
                run_index=1,
                validations={"1-2-3": IssueValidation(is_valid=True, argumentation="real bug", category="bug")},
            )
            == 1
        )

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
        # Two genuinely distinct issues from the same perspective on the same start line survive dedup with
        # different ids. They must NOT collapse to one issue_key (which would shadow a finding) and
        # each must pair to its OWN verdict (not the other's ruling).
        a = _issue("1-2-1", file="x.py", start=5, title="A", issue="problem A", suggestion="fix A")
        b = _issue(
            "1-2-2",
            file="x.py",
            start=5,
            title="B",
            issue="problem B",
            suggestion="fix B",
            priority=IssuePriority.SHOULD_FIX,
        )
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        assert persist_findings(team_id=self.team.id, report_id=report_id, issues=[a, b], run_index=1) == [
            "1-2-1",
            "1-2-2",
        ]
        assert (
            persist_verdicts(
                team_id=self.team.id,
                report_id=report_id,
                issues=[a, b],
                run_index=1,
                validations={
                    "1-2-1": IssueValidation(is_valid=True, argumentation="A is real"),
                    "1-2-2": IssueValidation(is_valid=False, argumentation="B dismissed"),
                },
            )
            == 2
        )

        finding_keys = {
            _content_as(ReviewIssueFinding, r.type, r.content).issue_key
            for r in ReviewReportArtefact.objects.for_team(self.team.id).filter(
                report_id=report_id, type=ReviewReportArtefact.ArtefactType.ISSUE_FINDING
            )
        }
        assert len(finding_keys) == 2
        verdicts = {
            v.issue_key: v
            for v in (
                _content_as(ValidationVerdict, r.type, r.content)
                for r in ReviewReportArtefact.objects.for_team(self.team.id).filter(
                    report_id=report_id, type=ReviewReportArtefact.ArtefactType.VALIDATION_VERDICT
                )
            )
        }
        assert set(verdicts) == finding_keys
        a_key = next(k for k in verdicts if k.endswith(":1-2-1"))
        b_key = next(k for k in verdicts if k.endswith(":1-2-2"))
        assert verdicts[a_key].is_valid is True
        assert verdicts[b_key].is_valid is False

    def test_verdict_not_written_for_issue_whose_finding_was_skipped(self) -> None:
        # An issue that fails durable finding validation must not leave behind an orphan verdict, even
        # when it has a validation result (the finding schema is stricter than the verdict's).
        good = _issue(
            "1-1-1", file="a.py", start=1, title="ok", issue="real description", priority=IssuePriority.CONSIDER
        )
        bad = _issue("1-1-2", file="b.py", start=1, title="bad", issue="   ", priority=IssuePriority.CONSIDER)
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        assert persist_findings(team_id=self.team.id, report_id=report_id, issues=[good, bad], run_index=1) == ["1-1-1"]
        assert (
            persist_verdicts(
                team_id=self.team.id,
                report_id=report_id,
                issues=[good, bad],
                run_index=1,
                validations={
                    "1-1-1": IssueValidation(is_valid=True, argumentation="ok"),
                    "1-1-2": IssueValidation(is_valid=True, argumentation="orphan ruling"),
                },
            )
            == 1
        )

        verdicts = [
            _content_as(ValidationVerdict, r.type, r.content)
            for r in ReviewReportArtefact.objects.for_team(self.team.id).filter(
                report_id=report_id, type=ReviewReportArtefact.ArtefactType.VALIDATION_VERDICT
            )
        ]
        assert len(verdicts) == 1
        assert verdicts[0].issue_key.endswith(":1-1-1")

    def test_persist_findings_skips_unpersistable_and_keeps_the_rest(self) -> None:
        # A single malformed LLM finding (empty body) must not abort the whole batch.
        good = _issue(
            "1-1-1", file="a.py", start=1, title="ok", issue="real description", priority=IssuePriority.CONSIDER
        )
        bad = _issue("1-1-2", file="b.py", title="bad", lines=[], issue="   ", priority=IssuePriority.CONSIDER)
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        assert persist_findings(team_id=self.team.id, report_id=report_id, issues=[good, bad], run_index=1) == ["1-1-1"]

        rows = ReviewReportArtefact.objects.for_team(self.team.id).filter(
            report_id=report_id, type=ReviewReportArtefact.ArtefactType.ISSUE_FINDING
        )
        assert rows.count() == 1

    def test_load_run_issues_round_trips_persisted_findings_by_id(self) -> None:
        # Validate + body-build reload issues from the finding rows by id (only ids cross Temporal
        # payloads): a drift between _to_finding/_from_finding, or a broken id reconstruction from
        # issue_key, would silently feed validation wrong or missing issues.
        a = _issue(
            "1-2-1",
            file="x.py",
            start=5,
            title="A",
            issue="problem A",
            suggestion="fix A",
            is_directly_related_to_changes=True,
        )
        b = _issue(
            "1000-2-1",
            file="y.py",
            start=9,
            title="B",
            issue="problem B",
            suggestion="fix B",
            priority=IssuePriority.SHOULD_FIX,
            source_perspective="review-hog-blind-spots-general",
        )
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        persisted = persist_findings(team_id=self.team.id, report_id=report_id, issues=[a, b], run_index=1)
        assert persisted == ["1-2-1", "1000-2-1"]

        assert load_run_issues(team_id=self.team.id, report_id=report_id, run_index=1, issue_ids=persisted) == [a, b]
        # The id filter scopes to the requested subset (a chunk's slice of the survivors).
        assert load_run_issues(team_id=self.team.id, report_id=report_id, run_index=1, issue_ids=["1000-2-1"]) == [b]


class TestLoadValidFindings(BaseTest):
    def test_returns_only_valid_pairs_latest_wins(self) -> None:
        # Publish reads its inline comments from here: each issue_key's LATEST finding joined to its
        # LATEST verdict, keeping only the valid ones. A stale-row read or a kept-invalid would post
        # the wrong comments.
        valid = _issue("1-1-1", file="a.py", title="keep me", issue="real")
        invalid = _issue("1-1-2", file="b.py", title="drop me", issue="not real")
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        persist_findings(team_id=self.team.id, report_id=report_id, issues=[valid, invalid], run_index=1)
        persist_verdicts(
            team_id=self.team.id,
            report_id=report_id,
            issues=[valid, invalid],
            run_index=1,
            validations={
                "1-1-1": IssueValidation(is_valid=True, argumentation="real"),
                "1-1-2": IssueValidation(is_valid=False, argumentation="not real"),
            },
        )

        pairs = load_valid_findings(team_id=self.team.id, report_id=report_id, run_index=1)
        assert len(pairs) == 1
        finding, verdict = pairs[0]
        assert finding.title == "keep me"
        assert verdict.is_valid is True
        assert verdict.issue_key == finding.issue_key

    def test_latest_verdict_overrides_an_earlier_one(self) -> None:
        # A later turn can flip a verdict; the latest row wins, so a finding first dismissed then
        # confirmed must publish (and vice versa). Guards the loop-y re-review contract.
        issue = _issue("1-1-1", file="a.py", title="flip", issue="real")
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        persist_findings(team_id=self.team.id, report_id=report_id, issues=[issue], run_index=1)
        persist_verdicts(
            team_id=self.team.id,
            report_id=report_id,
            issues=[issue],
            run_index=1,
            validations={"1-1-1": IssueValidation(is_valid=False, argumentation="dismissed")},
        )
        assert load_valid_findings(team_id=self.team.id, report_id=report_id, run_index=1) == []

        persist_verdicts(
            team_id=self.team.id,
            report_id=report_id,
            issues=[issue],
            run_index=1,
            validations={"1-1-1": IssueValidation(is_valid=True, argumentation="actually real")},
        )
        pairs = load_valid_findings(team_id=self.team.id, report_id=report_id, run_index=1)
        assert len(pairs) == 1
        assert pairs[0][1].argumentation == "actually real"

    def test_scopes_findings_to_the_requested_run(self) -> None:
        # Guards the duplicate-comment bug: publishing once replayed the whole finding history. Each
        # run's findings must stay scoped to that run, even when a later turn reuses the same id.
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        old = _issue("1-1-1", file="a.py", title="run-1 finding", issue="real")
        persist_findings(team_id=self.team.id, report_id=report_id, issues=[old], run_index=1)
        persist_verdict(
            team_id=self.team.id,
            report_id=report_id,
            issue=old,
            validation=IssueValidation(is_valid=True, argumentation="real"),
            run_index=1,
        )
        new = _issue("1-1-1", file="b.py", title="run-2 finding", issue="real")
        persist_findings(team_id=self.team.id, report_id=report_id, issues=[new], run_index=2)
        persist_verdict(
            team_id=self.team.id,
            report_id=report_id,
            issue=new,
            validation=IssueValidation(is_valid=True, argumentation="real"),
            run_index=2,
        )

        assert [f.title for f, _ in load_valid_findings(team_id=self.team.id, report_id=report_id, run_index=2)] == [
            "run-2 finding"
        ]
        assert [f.title for f, _ in load_valid_findings(team_id=self.team.id, report_id=report_id, run_index=1)] == [
            "run-1 finding"
        ]


class TestLoadRunValidations(BaseTest):
    def test_maps_issues_to_this_runs_verdicts_and_ignores_other_runs(self) -> None:
        # Powers validator skip-resume + DB-sourced body: each issue → this run's verdict (lossless),
        # unjudged issues absent, and an earlier run's verdict for the same id must not leak in.
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        judged = _issue("1-1-1", file="a.py")
        unjudged = _issue("1-1-2", file="b.py", start=20)
        persist_verdict(
            team_id=self.team.id,
            report_id=report_id,
            issue=judged,
            validation=IssueValidation(is_valid=True, argumentation="real", category="bug"),
            run_index=2,
        )
        # Same issue id, but an EARLIER run — keyed under run 1, so run 2's view must not return it.
        persist_verdict(
            team_id=self.team.id,
            report_id=report_id,
            issue=judged,
            validation=IssueValidation(is_valid=False, argumentation="stale", category="security"),
            run_index=1,
        )

        out = load_run_validations(team_id=self.team.id, report_id=report_id, run_index=2, issues=[judged, unjudged])

        assert set(out) == {"1-1-1"}  # the unjudged issue has no verdict this run
        assert out["1-1-1"].is_valid is True
        assert out["1-1-1"].category == "bug"
        assert out["1-1-1"].argumentation == "real"  # run 2's verdict, not run 1's "stale"

    def test_adjusted_priority_round_trips_through_the_verdict(self) -> None:
        # The validator's priority override must survive persist → load so the body + publish gates see
        # the adjusted severity; an unset override stays None (the no-migration default).
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        raised = _issue("1-1-1", file="a.py", priority=IssuePriority.CONSIDER)
        unchanged = _issue("1-1-2", file="b.py", start=20, priority=IssuePriority.MUST_FIX)
        persist_verdict(
            team_id=self.team.id,
            report_id=report_id,
            issue=raised,
            validation=IssueValidation(
                is_valid=True, argumentation="actually critical", adjusted_priority=IssuePriority.MUST_FIX
            ),
            run_index=1,
        )
        persist_verdict(
            team_id=self.team.id,
            report_id=report_id,
            issue=unchanged,
            validation=IssueValidation(is_valid=True, argumentation="as flagged"),
            run_index=1,
        )

        out = load_run_validations(team_id=self.team.id, report_id=report_id, run_index=1, issues=[raised, unchanged])

        assert out["1-1-1"].adjusted_priority == IssuePriority.MUST_FIX
        assert out["1-1-2"].adjusted_priority is None


class TestLoadPriorFindings(BaseTest):
    def test_returns_only_earlier_turns_findings(self) -> None:
        # The "already covered" context for a re-review must be PRIOR turns' findings only — never the
        # current turn's own, which would tell the agent to skip the very issues it's there to find.
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        persist_findings(
            team_id=self.team.id,
            report_id=report_id,
            issues=[_issue("1-1-1", file="a.py", title="run-1 issue")],
            run_index=1,
        )
        persist_findings(
            team_id=self.team.id,
            report_id=report_id,
            issues=[_issue("1-1-1", file="b.py", title="run-2 issue")],
            run_index=2,
        )

        # Reviewing turn 2 sees turn 1's findings as covered, not its own; turn 1 has nothing prior.
        assert [
            f.title for f in load_prior_findings(team_id=self.team.id, report_id=report_id, before_run_index=2)
        ] == ["run-1 issue"]
        assert load_prior_findings(team_id=self.team.id, report_id=report_id, before_run_index=1) == []

    def test_with_verdicts_pairs_each_prior_finding_with_its_ruling(self) -> None:
        # Dedup drops a re-found problem citing the earlier ruling — pairing the wrong verdict (or a
        # current-turn finding) would suppress fresh issues or re-litigate settled ones.
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        judged = _issue("1-1-1", file="a.py", title="judged")
        persist_findings(team_id=self.team.id, report_id=report_id, issues=[judged], run_index=1)
        persist_findings(
            team_id=self.team.id,
            report_id=report_id,
            issues=[_issue("1-1-2", file="b.py", title="unjudged")],
            run_index=1,
        )
        persist_verdict(
            team_id=self.team.id,
            report_id=report_id,
            issue=judged,
            validation=IssueValidation(is_valid=False, argumentation="not real"),
            run_index=1,
        )

        pairs = load_prior_findings_with_verdicts(team_id=self.team.id, report_id=report_id, before_run_index=2)

        by_title = {finding.title: verdict for finding, verdict in pairs}
        assert by_title["judged"] is not None and by_title["judged"].is_valid is False
        assert by_title["unjudged"] is None


# The per-turn working-state rows that back the DB-driven resume.
class TestWorkingState(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report_id = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha-aaa")
        )

    def _chunks(self) -> ChunksList:
        return ChunksList(chunks=[Chunk(chunk_id=1, files=[FileInfo(filename="a.py")], chunk_type="feature")])

    def test_chunk_set_round_trips_and_is_scoped_to_its_head_sha(self) -> None:
        # Resume reuses the chunking only for the current head; a new head must re-chunk, not reuse a
        # prior turn's chunks (line numbers would be wrong).
        persist_chunk_set(team_id=self.team.id, report_id=self.report_id, head_sha="sha-aaa", chunks=self._chunks())
        loaded = load_chunk_set(team_id=self.team.id, report_id=self.report_id, head_sha="sha-aaa")
        assert loaded is not None
        assert [c.chunk_id for c in loaded.chunks] == [1]
        assert load_chunk_set(team_id=self.team.id, report_id=self.report_id, head_sha="sha-bbb") is None

    def test_chunk_set_with_duplicate_ids_degrades_to_absent_instead_of_crashing(self) -> None:
        # The unique-chunk_id invariant lives on ChunksList, which the per-Chunk artefact parse never
        # runs — only load_chunk_set's reassembly does. A bad persisted row (pre-validator local data
        # or a future writer bug) must degrade like any unparseable row (None → the stage re-runs),
        # not crash every resume of the turn with a raw ValidationError.
        ReviewReportArtefact.add_working_state(
            team_id=self.team.id,
            report_id=self.report_id,
            content=ChunkSetArtefact(
                head_sha="sha-aaa",
                chunks=[
                    Chunk(chunk_id=1, files=[FileInfo(filename="a.py")]),
                    Chunk(chunk_id=1, files=[FileInfo(filename="b.py")]),
                ],
            ),
            attribution=ArtefactAttribution.system(),
        )

        assert load_chunk_set(team_id=self.team.id, report_id=self.report_id, head_sha="sha-aaa") is None

    def test_perspective_results_round_trip_keyed_by_pass_and_chunk(self) -> None:
        results = {
            (1, 1): IssuesReview(issues=[_issue("1-1-1")]),
            (2, 1): IssuesReview(issues=[_issue("2-1-1")]),
        }
        persist_perspective_results(team_id=self.team.id, report_id=self.report_id, head_sha="sha-aaa", results=results)
        loaded = load_perspective_results(team_id=self.team.id, report_id=self.report_id, head_sha="sha-aaa")
        assert set(loaded.keys()) == {(1, 1), (2, 1)}
        assert loaded[(1, 1)].issues[0].id == "1-1-1"
        assert load_perspective_results(team_id=self.team.id, report_id=self.report_id, head_sha="sha-bbb") == {}


class TestPersistCommitSnapshot(BaseTest):
    def _commits(self, report_id: str):
        return ReviewReportArtefact.objects.for_team(self.team.id).filter(
            report_id=report_id, type=ReviewReportArtefact.ArtefactType.COMMIT
        )

    def test_snapshot_stores_the_diff_at_head_sha_and_advances_both_watermarks(self) -> None:
        # The point-in-time guarantee: the reviewed diff is captured against the exact head_sha and
        # the watermark advances so a later turn knows what was reviewed. A dropped diff, a wrong
        # sha, or a forgotten watermark bump would all surface here.
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
            diff="=== a.py [modified] ===\n@@ -1 +1 @@\n-old\n+new",
        )

        assert appended is True
        row = self._commits(report_id).get()
        commit = parse_artefact_content(row.type, row.content)
        assert isinstance(commit, Commit)
        assert commit.commit_sha == "sha-aaa"
        assert commit.diff == "=== a.py [modified] ===\n@@ -1 +1 @@\n-old\n+new"
        assert row.created_by_id is None
        assert row.task_id is None
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.head_sha == "sha-aaa"
        assert report.last_seen_comment_id == 11

    def test_snapshot_is_idempotent_when_head_sha_is_unchanged(self) -> None:
        # A re-run with no new commits must not duplicate the snapshot — this is exactly the loop's
        # no-op turn. Without the watermark guard the report would accrete identical snapshots forever.
        report_id = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha-aaa")
        )
        first = persist_commit_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            repository="o/r",
            pr_metadata=_pr_metadata(head_sha="sha-aaa"),
            pr_comments=[],
            diff="@@ -1 +1 @@",
        )
        second = persist_commit_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            repository="o/r",
            pr_metadata=_pr_metadata(head_sha="sha-aaa"),
            pr_comments=[],
            diff="@@ -1 +1 @@",
        )
        assert first is True
        assert second is False
        assert self._commits(report_id).count() == 1

    def test_new_head_sha_appends_a_second_snapshot(self) -> None:
        # When the PR head actually moves, the new turn must append its own snapshot (never mutate
        # the prior one) so the per-turn history survives later force-pushes.
        report_id = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha-aaa")
        )
        persist_commit_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            repository="o/r",
            pr_metadata=_pr_metadata(head_sha="sha-aaa"),
            pr_comments=[],
            diff="turn-1 diff",
        )
        appended = persist_commit_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            repository="o/r",
            pr_metadata=_pr_metadata(head_sha="sha-bbb"),
            pr_comments=[],
            diff="turn-2 diff",
        )
        assert appended is True
        diffs = {_content_as(Commit, r.type, r.content).diff for r in self._commits(report_id)}
        assert diffs == {"turn-1 diff", "turn-2 diff"}
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.head_sha == "sha-bbb"

    def test_snapshot_skipped_when_head_sha_missing(self) -> None:
        # No head_sha (a degraded fetch) must skip cleanly rather than build a Commit with a blank
        # sha (which the schema rejects) or advance the watermark.
        report_id = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha=None)
        )
        appended = persist_commit_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            repository="o/r",
            pr_metadata=_pr_metadata(head_sha=None),
            pr_comments=[],
            diff="some diff",
        )
        assert appended is False
        assert self._commits(report_id).count() == 0
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).head_sha is None

    def test_snapshot_records_empty_diff_when_no_reviewable_files(self) -> None:
        # An empty diff is a legitimate "everything filtered out" turn: record the commit with
        # diff=None and advance the watermark, rather than skip.
        report_id = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha-aaa")
        )
        appended = persist_commit_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            repository="o/r",
            pr_metadata=_pr_metadata(head_sha="sha-aaa"),
            pr_comments=[],
            diff="",
        )
        assert appended is True
        commit = _content_as(Commit, *self._commits(report_id).values_list("type", "content").get())
        assert commit.diff is None
        assert commit.commit_sha == "sha-aaa"
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).head_sha == "sha-aaa"


class TestPRSnapshot(BaseTest):
    def test_round_trips_and_is_head_scoped(self) -> None:
        # The by-reference reload the Temporal stage activities depend on: the fetch persists the PR
        # inputs once, every later activity reloads them by (report_id, head_sha). A broken head tag
        # or working-state load would silently strand the whole fan-out, so guard the round-trip and
        # the head scoping.
        report_id = upsert_review_report(
            team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata(head_sha="sha1")
        )
        persist_pr_snapshot(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="sha1",
            pr_metadata=_pr_metadata(head_sha="sha1"),
            pr_comments=[PRComment(path="a.py", line=3, body="b", diff_hunk="", user="u", created_at="2026-01-01")],
            pr_files=[],
        )

        loaded = load_pr_snapshot(team_id=self.team.id, report_id=report_id, head_sha="sha1")
        assert loaded is not None
        assert loaded.pr_metadata.number == 123
        assert [c.path for c in loaded.pr_comments] == ["a.py"]
        # A different head returns nothing — resume reuses only the current turn's inputs.
        assert load_pr_snapshot(team_id=self.team.id, report_id=report_id, head_sha="other") is None


class TestPersistVerdict(BaseTest):
    def test_persist_verdict_pairs_with_its_finding_by_issue_key(self) -> None:
        # The per-issue validate fan-out persists one verdict per issue; it must pair 1:1 with the
        # finding dedup wrote (shared issue_key) so load_valid_findings joins them. A drifted key would
        # orphan the verdict and drop the finding from publish.
        report_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="u", pr_metadata=_pr_metadata())
        issue = _issue("1-1-1")
        persist_findings(team_id=self.team.id, report_id=report_id, issues=[issue], run_index=1)
        wrote = persist_verdict(
            team_id=self.team.id,
            report_id=report_id,
            issue=issue,
            validation=IssueValidation(is_valid=True, argumentation="reachable bug", category="bug"),
            run_index=1,
        )

        assert wrote is True
        pairs = load_valid_findings(team_id=self.team.id, report_id=report_id, run_index=1)
        assert len(pairs) == 1
        finding, verdict = pairs[0]
        assert verdict.is_valid is True
        assert verdict.argumentation == "reachable bug"
        assert verdict.issue_key == finding.issue_key
