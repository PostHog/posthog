import pytest
from posthog.test.base import BaseTest

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    ARTEFACT_CONTENT_SCHEMAS,
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ArtefactContentValidationError, TaskRunArtefact


def _finding(issue_key: str = "f.py:10:logic") -> ReviewIssueFinding:
    return ReviewIssueFinding(
        issue_key=issue_key,
        title="Off-by-one",
        file="f.py",
        lines=[LineRange(start=10)],
        body="loop runs one short",
        suggestion="use <=",
        priority=IssuePriority.MUST_FIX,
    )


class TestReviewArtefactContent:
    def test_registry_keys_match_artefact_type_enum(self):
        # Adding an ArtefactType choice without registering its content schema (or vice versa)
        # silently breaks parse_artefact_content / artefact_type_for for that type.
        assert set(ARTEFACT_CONTENT_SCHEMAS.keys()) == set(ReviewReportArtefact.ArtefactType.values)

    def test_add_log_rejects_non_log_content(self):
        # add_log must refuse a finding — only task_run/commit/code_reference/note accumulate via it.
        with pytest.raises(ValueError):
            ReviewReportArtefact.add_log(
                team_id=1,
                report_id="r",
                content=_finding(),
                attribution=ArtefactAttribution.from_user(1),
            )

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
        assert parsed.issue_key == "f.py:10:logic"
        assert parsed.priority == IssuePriority.MUST_FIX

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
