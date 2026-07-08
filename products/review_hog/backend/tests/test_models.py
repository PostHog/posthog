import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    ARTEFACT_CONTENT_SCHEMAS,
    ChunkSetArtefact,
    PerspectiveResultArtefact,
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, FileInfo
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ArtefactContentValidationError, TaskRunArtefact


def _finding(issue_key: str = "r1:f.py:10:logic") -> ReviewIssueFinding:
    return ReviewIssueFinding(
        issue_key=issue_key,
        run_index=1,
        title="Off-by-one",
        file="f.py",
        lines=[LineRange(start=10)],
        body="loop runs one short",
        suggestion="use <=",
        priority=IssuePriority.MUST_FIX,
    )


def _chunk_set(head_sha: str = "abc123") -> ChunkSetArtefact:
    return ChunkSetArtefact(
        head_sha=head_sha,
        chunks=[Chunk(chunk_id=1, files=[FileInfo(filename="f.py")], chunk_type="business_logic")],
    )


def _perspective_result(head_sha: str = "abc123") -> PerspectiveResultArtefact:
    return PerspectiveResultArtefact(head_sha=head_sha, pass_number=1, chunk_id=1, review=IssuesReview(issues=[]))


class TestReviewArtefactContent:
    def test_registry_keys_match_artefact_type_enum(self):
        # Adding an ArtefactType choice without registering its content schema (or vice versa)
        # silently breaks parse_artefact_content / artefact_type_for for that type.
        assert set(ARTEFACT_CONTENT_SCHEMAS.keys()) == set(ReviewReportArtefact.ArtefactType.values)
        # The working-state types the DB-driven resume reads back must be registered.
        assert {"chunk_set", "perspective_result"} <= set(ARTEFACT_CONTENT_SCHEMAS.keys())

    @parameterized.expand([("finding", _finding), ("chunk_set", _chunk_set)])
    def test_add_log_rejects_non_log_content(self, _name, make_content):
        # add_log must refuse findings and working-state content — only
        # task_run/commit/code_reference/note accumulate via it. Raises before any DB write.
        with pytest.raises(ValueError):
            ReviewReportArtefact.add_log(
                team_id=1,
                report_id="r",
                content=make_content(),
                attribution=ArtefactAttribution.from_user(1),
            )

    def test_add_working_state_rejects_non_working_state_content(self):
        # add_working_state must refuse a finding — only chunk_set/perspective_result/pr_snapshot
        # accumulate via it. Raises before any DB write.
        with pytest.raises(ValueError):
            ReviewReportArtefact.add_working_state(
                team_id=1,
                report_id="r",
                content=_finding(),  # type: ignore[arg-type]  # the rejection under test
                attribution=ArtefactAttribution.system(),
            )

    def test_verdict_parses_legacy_row_without_adjusted_priority(self):
        # adjusted_priority was added without a migration: a verdict row written before it must parse
        # with the field defaulting to None rather than raising.
        legacy = '{"issue_key": "k", "is_valid": true, "argumentation": "real"}'
        verdict = parse_artefact_content("validation_verdict", legacy)
        assert isinstance(verdict, ValidationVerdict)
        assert verdict.adjusted_priority is None

    def test_create_rejects_task_run_with_mismatched_task(self):
        # The task_run's content.task_id is the same association as the row's task FK; the guard
        # stops them diverging. Raises before any DB write.
        with pytest.raises(ArtefactContentValidationError):
            ReviewReportArtefact.add_log(
                team_id=1,
                report_id="r",
                content=TaskRunArtefact(task_id="task-A", product="review_hog", type="review"),
                attribution=ArtefactAttribution.from_task("task-B"),
            )


class TestReviewArtefactFunnel(BaseTest):
    def _report(self) -> ReviewReport:
        # ReviewReport is fail-closed (TeamScopedRootMixin), so creation outside request context
        # goes through for_team — the same path the funnel uses.
        return ReviewReport.objects.for_team(self.team.id).create(
            team=self.team,
            repository="o/r",
            pr_number=1,
            pr_url="https://github.com/o/r/pull/1",
            head_branch="feat",
            base_branch="main",
        )

    def test_finding_funnel_persists_type_attribution_and_content(self):
        report = self._report()
        artefact = ReviewReportArtefact.append_finding(
            team_id=self.team.id,
            report_id=str(report.id),
            content=_finding(),
            attribution=ArtefactAttribution.from_user(self.user.id),
        )
        # type is derived from the content model's class, not passed in.
        assert artefact.type == ReviewReportArtefact.ArtefactType.ISSUE_FINDING
        # user attribution maps to created_by; task stays null (a swap of the two columns fails here).
        assert artefact.created_by_id == self.user.id
        assert artefact.task_id is None
        # content survives the JSON round-trip with its typed shape.
        parsed = parse_artefact_content(artefact.type, artefact.content)
        assert isinstance(parsed, ReviewIssueFinding)
        assert parsed.issue_key == "r1:f.py:10:logic"
        assert parsed.priority == IssuePriority.MUST_FIX

    @parameterized.expand(
        [
            (_chunk_set, ReviewReportArtefact.ArtefactType.CHUNK_SET, ChunkSetArtefact),
            (_perspective_result, ReviewReportArtefact.ArtefactType.PERSPECTIVE_RESULT, PerspectiveResultArtefact),
        ]
    )
    def test_working_state_funnel_derives_type_and_round_trips_content(self, make_content, expected_type, model_cls):
        report = self._report()
        content = make_content()
        artefact = ReviewReportArtefact.add_working_state(
            team_id=self.team.id,
            report_id=str(report.id),
            content=content,
            attribution=ArtefactAttribution.system(),
        )
        # type is derived from the content model's class, not passed in.
        assert artefact.type == expected_type
        # system attribution leaves both columns null.
        assert artefact.created_by_id is None
        assert artefact.task_id is None
        # head_sha-scoped content survives the JSON round-trip with its typed shape.
        parsed = parse_artefact_content(artefact.type, artefact.content)
        assert isinstance(parsed, model_cls)
        assert parsed == content

    def test_verdict_funnel_derives_type_and_system_attribution_is_null(self):
        report = self._report()
        artefact = ReviewReportArtefact.append_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ValidationVerdict(
                issue_key="f.py:10:logic", is_valid=True, argumentation="real bug", category="bug"
            ),
            attribution=ArtefactAttribution.system(),
        )
        assert artefact.type == ReviewReportArtefact.ArtefactType.VALIDATION_VERDICT
        # system attribution leaves both columns null.
        assert artefact.created_by_id is None
        assert artefact.task_id is None
