from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration

from products.review_hog.backend.facade.review_status_types import HeadReviewState
from products.review_hog.backend.head_review_status import HeadReviewStatusLookup
from products.review_hog.backend.models import ReviewInstallationClaim, ReviewReport, ReviewReportArtefact
from products.review_hog.backend.receivers import review_evidence_for_stamphog
from products.review_hog.backend.reviewer.artefact_content import (
    ReviewIssueFinding,
    TurnMarkerArtefact,
    ValidationVerdict,
)
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.progress import record_run_outcome
from products.review_hog.backend.temporal.client import QueuedReviewHeads
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.stamphog.backend.facade.review_evidence import ReviewEvidenceState, get_review_evidence_providers

REPOSITORY = "PostHog/posthog"
HEAD = "sha1"
OLDER_HEAD = "sha0"
_QUEUE = "products.review_hog.backend.head_review_status.queued_review_heads"


class TestHeadReviewStatus(BaseTest):
    def _report(self, **fields: object) -> ReviewReport:
        values: dict = {
            "team_id": self.team.id,
            "repository": REPOSITORY,
            "pr_number": 5,
            "pr_url": "https://github.com/PostHog/posthog/pull/5",
            "head_branch": "feat",
            "base_branch": "main",
            "status": ReviewReport.Status.IDLE,
            **fields,
        }
        return ReviewReport.objects.for_team(self.team.id).create(**values)

    def _completed_turn(
        self, review_mode: str, head_sha: str = HEAD, publishes: bool = True, **fields: object
    ) -> ReviewReport:
        report = self._report(run_count=1, head_sha=head_sha, completed_head_sha=head_sha, **fields)
        ReviewReportArtefact.add_turn_marker(
            team_id=self.team.id,
            report_id=str(report.id),
            content=TurnMarkerArtefact(
                head_sha=head_sha,
                run_index=1,
                review_mode=review_mode,
                reviewhog_version="v",
                reviewhog_fingerprint="f",
                publishes=publishes,
                base_branch="main",
                skipped_paths=["pnpm-lock.yaml"],
            ),
            attribution=ArtefactAttribution.system(),
        )
        return report

    def _move_failure(self, report: ReviewReport, offset: timedelta) -> None:
        # Two writes in a row can share a timestamp, so the test sets the order the case needs.
        artefacts = ReviewReportArtefact.objects.for_team(self.team.id).filter(report_id=report.id)
        marker = artefacts.get(type=ReviewReportArtefact.ArtefactType.TURN_MARKER)
        artefacts.filter(type=ReviewReportArtefact.ArtefactType.NOTE).update(created_at=marker.created_at + offset)

    def _finding(self, report: ReviewReport, key: str, *, is_valid: bool) -> None:
        ReviewReportArtefact.append_finding(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ReviewIssueFinding(
                issue_key=key,
                run_index=1,
                title="t",
                file="f.py",
                lines=[LineRange(start=1)],
                body="b",
                suggestion="s",
                priority=IssuePriority.MUST_FIX,
            ),
            attribution=ArtefactAttribution.system(),
        )
        ReviewReportArtefact.append_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ValidationVerdict(issue_key=key, is_valid=is_valid, argumentation="a"),
            attribution=ArtefactAttribution.system(),
        )

    def _failed(self, report: ReviewReport, run_index: int) -> None:
        record_run_outcome(
            self.team.id,
            str(report.id),
            stage="review",
            outcome="failed",
            reason="review_failed",
            run_index=run_index,
            review_mode=REVIEW_MODE_FLASH,
            head_sha=HEAD,
        )

    def _nothing(self) -> None:
        pass

    def _running_turn(self) -> None:
        self._report(status=ReviewReport.Status.ACTIVE, run_count=0, head_sha=HEAD)

    def _publish_window(self) -> None:
        # Finalize already counted the turn, and the report stays ACTIVE until its findings are posted.
        self._completed_turn(REVIEW_MODE_FLASH, status=ReviewReport.Status.ACTIVE)

    def _turn_running_on_older_head(self) -> None:
        self._report(status=ReviewReport.Status.ACTIVE, run_count=0, head_sha=OLDER_HEAD)

    def _clean_standard_turn(self) -> None:
        self._completed_turn(REVIEW_MODE_FLASH)

    def _deep_turn_with_published_findings(self) -> None:
        report = self._completed_turn(REVIEW_MODE_FULL, published_head_shas={"1": HEAD})
        self._finding(report, "1-a", is_valid=True)
        self._finding(report, "1-b", is_valid=True)
        self._finding(report, "1-c", is_valid=False)

    def _eval_turn_with_findings(self) -> None:
        report = self._completed_turn(REVIEW_MODE_FULL, publishes=False)
        self._finding(report, "1-a", is_valid=True)

    def _turn_on_older_head(self) -> None:
        self._completed_turn(REVIEW_MODE_FLASH, head_sha=OLDER_HEAD)

    def _failed_first_turn(self) -> None:
        self._failed(self._report(run_count=0, head_sha=HEAD), run_index=1)

    def _failed_publish(self) -> None:
        report = self._completed_turn(REVIEW_MODE_FLASH)
        self._failed(report, run_index=1)
        self._move_failure(report, timedelta(minutes=1))

    def _retry_after_a_failed_attempt(self) -> None:
        report = self._completed_turn(REVIEW_MODE_FLASH)
        self._failed(report, run_index=1)
        self._move_failure(report, -timedelta(minutes=1))

    @parameterized.expand(
        [
            ("queued_request_for_the_head", "_nothing", ([], [HEAD]), (HeadReviewState.PENDING, "", 0, False)),
            ("queued_request_for_the_live_head", "_nothing", ([], [None]), (HeadReviewState.PENDING, "", 0, False)),
            ("queued_request_for_another_head", "_nothing", ([], [OLDER_HEAD]), None),
            ("running_turn", "_running_turn", ([], []), (HeadReviewState.PENDING, "", 0, False)),
            ("publish_window", "_publish_window", ([], []), (HeadReviewState.PENDING, "", 0, False)),
            # The active request without a head is the turn that runs on the older head.
            ("headless_request_of_a_turn_on_another_head", "_turn_running_on_older_head", ([None], []), None),
            # A waiting request without a head reviews the live head after the running turn ends.
            (
                "headless_request_waiting_behind_a_turn_on_another_head",
                "_turn_running_on_older_head",
                ([None], [None]),
                (HeadReviewState.PENDING, "", 0, False),
            ),
            (
                "clean_standard_turn",
                "_clean_standard_turn",
                ([], []),
                (HeadReviewState.COMPLETED, "Standard", 0, False),
            ),
            (
                "deep_turn_with_published_findings",
                "_deep_turn_with_published_findings",
                ([], []),
                (HeadReviewState.COMPLETED, "Deep", 2, True),
            ),
            # An eval or CLI turn posts nothing to the PR, so it is no review of the PR.
            ("eval_turn_with_findings", "_eval_turn_with_findings", ([], []), None),
            ("turn_on_an_older_head", "_turn_on_older_head", ([], []), None),
            ("failed_turn", "_failed_first_turn", ([], []), (HeadReviewState.FAILED, "", 0, False)),
            ("failed_publish", "_failed_publish", ([], []), (HeadReviewState.FAILED, "", 0, False)),
            (
                "retry_after_a_failed_attempt",
                "_retry_after_a_failed_attempt",
                ([], []),
                (HeadReviewState.COMPLETED, "Standard", 0, False),
            ),
        ]
    )
    def test_status_of_the_head(
        self,
        _name: str,
        scenario: str,
        queued_heads: tuple[list[str | None], list[str | None]],
        expected: tuple[HeadReviewState, str, int, bool] | None,
    ) -> None:
        getattr(self, scenario)()

        active, pending = queued_heads
        with patch(_QUEUE, return_value=QueuedReviewHeads(active=tuple(active), pending=tuple(pending))):
            status = HeadReviewStatusLookup(self.team.id, "posthog/PostHog", 5, HEAD).status()

        if expected is None:
            assert status is None
            return
        assert status is not None
        assert (status.state, status.review_kind, status.findings_count, status.published) == expected
        assert status.head_sha == HEAD

    @parameterized.expand([("owned", True), ("not_owned", False)])
    def test_provider_answers_only_for_a_repository_a_project_reviews(self, _name: str, owned: bool) -> None:
        # A lost registration in AppConfig.ready() would leave stamphog without this reviewer, silently.
        assert review_evidence_for_stamphog in get_review_evidence_providers()
        Integration.objects.create(
            team=self.team, kind="github", integration_id="1001", config={"account": {"name": "PostHog"}}
        )
        if owned:
            ReviewInstallationClaim.objects.for_team(self.team.id).create(
                team=self.team, installation_id="1001", scope=ReviewInstallationClaim.Scope.ALL
            )
        self._clean_standard_turn()

        with patch(_QUEUE, return_value=QueuedReviewHeads()):
            evidence = review_evidence_for_stamphog(REPOSITORY, 5, HEAD)

        if owned:
            assert evidence is not None
            assert (
                evidence.state,
                evidence.reviewer,
                evidence.review_kind,
                evidence.base_ref,
                evidence.skipped_paths,
            ) == (ReviewEvidenceState.COMPLETED, "PostHog Review", "Standard", "main", ("pnpm-lock.yaml",))
        else:
            assert evidence is None
