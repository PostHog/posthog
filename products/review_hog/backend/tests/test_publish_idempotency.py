from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.instance_setting import override_instance_config

from products.review_hog.backend.facade.enums import ReviewRequestOutcomeStatus
from products.review_hog.backend.facade.review_status_types import HeadReviewState
from products.review_hog.backend.head_review_status import HeadReviewStatusLookup
from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.pr_status import PRStatusLookup
from products.review_hog.backend.review_request_rules import full_review_published
from products.review_hog.backend.reviewer.artefact_content import (
    PRSnapshotArtefact,
    ReviewIssueFinding,
    TurnMarkerArtefact,
    ValidationVerdict,
)
from products.review_hog.backend.reviewer.constants import LEGACY_FLASH_MODE_MESSAGE_PREFIX
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import DroppedIssue, Issue, IssuePriority
from products.review_hog.backend.reviewer.persistence import replace_dropped_findings, upsert_review_report
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.review_hog.backend.reviewer.tools.publish_review import (
    PublishOutcome,
    _review_already_posted,
    _review_marker,
)
from products.review_hog.backend.temporal.activities import PublishInput, _fail_run, _publish, publish_review_activity
from products.review_hog.backend.temporal.client import QueuedReviewHeads, WorkflowProbe
from products.signals.backend.facade.taxonomy import ArtefactAttribution

# `_publish` now delegates to `publish_persisted_review` in the tool, so the GitHub-post seam and the
# snapshot load are patched there; the installation auth is still resolved in the activity wrapper.
_PUBLISH = "products.review_hog.backend.reviewer.tools.publish_review.publish_review"
_SNAPSHOT = "products.review_hog.backend.reviewer.tools.publish_review.load_pr_snapshot"
_AUTH = "products.review_hog.backend.temporal.activities._installation_auth"
pytestmark = pytest.mark.django_db

_PAGINATED = "products.review_hog.backend.reviewer.tools.publish_review.github_api_get_paginated"
_ACTIVITIES = "products.review_hog.backend.temporal.activities"


def _paginated(
    items: list[dict[str, Any]], *, boom: bool = False, status: int = 500
) -> Callable[..., Iterator[dict[str, Any]]]:
    """A github_api_get_paginated stand-in yielding `items` (or failing the readback with `boom`)."""

    def fake(path: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        if boom:
            raise GitHubAPIError("readback failed", status=status)
        return iter(items)

    return fake


def _review_posted(marker: str, reviews: list[dict[str, Any]], *, boom: bool = False) -> bool:
    with patch(_PAGINATED, side_effect=_paginated(reviews, boom=boom)):
        return _review_already_posted("o", "r", 1, marker, token="t", installation_id=None)


def test_review_already_posted_detects_our_own_markered_review() -> None:
    # Post-then-crash backstop: a review we posted (an app-bot review) carries this run's marker, so
    # a retry recognizes it and skips. A review without the marker (another turn/author) must not
    # match — and neither may a human review carrying a pasted marker: on a public repo anyone can
    # copy it, and a match here silently suppresses the publish.
    marker = _review_marker("rep-1", "sha1")
    bot = {"user": {"login": "posthog[bot]", "type": "Bot"}}
    assert _review_posted(marker, [{"body": f"body text\n\n{marker}", **bot}]) is True
    assert _review_posted(marker, [{"body": "an unrelated review", **bot}, {"body": None, **bot}]) is False
    assert _review_posted(marker, [{"body": _review_marker("rep-1", "other-sha"), **bot}]) is False
    assert (
        _review_posted(marker, [{"body": f"pasted: {marker}", "user": {"login": "prankster", "type": "User"}}]) is False
    )
    assert _review_posted(marker, [{"body": f"no user field: {marker}"}]) is False
    # With the app's bot login configured, another installed bot's pasted marker must not match either.
    with override_instance_config("GITHUB_APP_SLUG", "posthog"):
        assert _review_posted(marker, [{"body": marker, **bot}]) is True
        assert _review_posted(marker, [{"body": marker, "user": {"login": "rogue[bot]", "type": "Bot"}}]) is False
    # Unconfigured in production, no bot is trusted, because any installed bot could paste the marker.
    with override_instance_config("GITHUB_APP_SLUG", ""), override_settings(DEBUG=False, TEST=False):
        assert _review_posted(marker, [{"body": marker, **bot}]) is False


def test_review_already_posted_proceeds_when_readback_fails() -> None:
    # Best-effort: if listing reviews errors we post rather than silently drop the review (the
    # published_head_sha watermark still guards the common retry path).
    with patch(_PAGINATED, side_effect=_paginated([], boom=True, status=404)):
        assert (
            _review_already_posted("o", "r", 1, _review_marker("rep-1", "sha1"), token="t", installation_id=None)
            is False
        )


def test_review_already_posted_raises_on_a_transient_readback_failure() -> None:
    # An earlier attempt may have posted already, so posting blind on a 5xx risks a second review.
    with pytest.raises(GitHubAPIError):
        _review_posted(_review_marker("rep-1", "sha1"), [], boom=True)


@parameterized.expand(
    [
        ("full", ""),
        ("flash", "FLASH MODE\n"),
        ("flash", LEGACY_FLASH_MODE_MESSAGE_PREFIX),
    ]
)
def test_legacy_markers_only_suppress_reviews_in_the_same_mode(posted_mode: str, prefix: str) -> None:
    legacy = _review_marker("rep-1", "sha1")
    review = {"body": f"{prefix}body\n{legacy}", "user": {"type": "Bot"}}
    with patch(_PAGINATED, side_effect=_paginated([review])):
        for requested_mode in ("full", "flash"):
            assert _review_already_posted(
                "o",
                "r",
                1,
                _review_marker("rep-1", "sha1", requested_mode),
                token="t",
                installation_id=None,
                legacy_marker=legacy,
                review_mode=requested_mode,
            ) is (posted_mode == requested_mode)


def _publish_input(team_id: int, report_id: str, head_sha: str) -> PublishInput:
    return PublishInput(
        team_id=team_id,
        report_id=report_id,
        head_sha=head_sha,
        run_index=1,
        owner="PostHog",
        repo="posthog",
        pr_number=1,
        urgency_threshold="should_fix",
    )


def _pr_metadata(head_sha: str) -> PRMetadata:
    return PRMetadata(
        number=1,
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


class TestPublishIdempotency(BaseTest):
    @parameterized.expand(
        [
            ("findings", True, "refusal", False),
            ("clean", False, "refusal", False),
            ("manual_findings", True, None, False),
            ("manual_clean", False, None, False),
            ("refusal_publish_retry", True, "refusal", True),
            ("manual_publish_retry", True, None, True),
        ]
    )
    @patch(_AUTH, return_value=("tok", None))
    def test_refusal_publication_is_retryable_without_disabling_standard_reviews(
        self,
        _name: str,
        posted: bool,
        request_id: str | None,
        repair_completion: bool,
        _auth: MagicMock,
    ) -> None:
        report_id = self._report()
        requested_at = timezone.now()
        ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(
            published_heads_by_mode={"flash": "sha0"},
            published_head_shas={"1": "sha0"},
            run_count=2,
            head_sha="sha1",
            completed_head_sha="sha1",
            last_run_at=requested_at,
        )
        ReviewReportArtefact.add_turn_marker(
            team_id=self.team.id,
            report_id=report_id,
            content=TurnMarkerArtefact(
                head_sha="sha1",
                run_index=2,
                review_mode="full",
                reviewhog_version="test",
                reviewhog_fingerprint="test",
                stamphog_review_run_id=request_id,
                queue_turn_id="turn",
                publishes=True,
            ),
            attribution=ArtefactAttribution.system(),
        )
        if posted:
            ReviewReportArtefact.append_finding(
                team_id=self.team.id,
                report_id=report_id,
                content=ReviewIssueFinding(
                    issue_key="r2:missing-guard",
                    run_index=2,
                    title="Missing guard",
                    file="handler.py",
                    body="An absent value reaches the handler.",
                    suggestion="Check the value first.",
                    priority=IssuePriority.SHOULD_FIX,
                ),
                attribution=ArtefactAttribution.system(),
            )
            ReviewReportArtefact.append_verdict(
                team_id=self.team.id,
                report_id=report_id,
                content=ValidationVerdict(
                    issue_key="r2:missing-guard", is_valid=True, argumentation="The absent value reaches the handler."
                ),
                attribution=ArtefactAttribution.system(),
            )
        request = PublishInput(
            team_id=self.team.id,
            report_id=report_id,
            head_sha="sha1",
            run_index=2,
            queue_turn_id="turn" if request_id else None,
            owner="PostHog",
            repo="posthog",
            pr_number=1,
        )

        def statuses() -> tuple[HeadReviewState, ReviewRequestOutcomeStatus]:
            with (
                patch(
                    "products.review_hog.backend.head_review_status.queued_review_heads",
                    return_value=QueuedReviewHeads(),
                ),
                patch("products.review_hog.backend.pr_status.probe_workflow", return_value=WorkflowProbe.NOT_RUNNING),
            ):
                head = HeadReviewStatusLookup(self.team.id, "PostHog/posthog", 1, "sha1").status()
                pr = PRStatusLookup(self.team.id, "PostHog", "posthog", 1).status(requested_at, "full", "sha1")
            assert head is not None and pr.request_outcome is not None
            return head.state, pr.request_outcome.status

        with patch(f"{_ACTIVITIES}.fail_status_comment"):
            _fail_run(self.team.id, report_id, run_index=2)
        assert statuses() == (HeadReviewState.FAILED, ReviewRequestOutcomeStatus.FAILED)

        with (
            patch("products.review_hog.backend.reviewer.tools.publish_review.github_api_request") as github,
            patch(_PAGINATED, side_effect=lambda *args, **kwargs: iter([])),
            patch("products.review_hog.backend.reviewer.tools.publish_review.remove_own_pr_reactions"),
        ):
            github.return_value.json.return_value = {"html_url": "https://github.com/PostHog/posthog/pull/1#review-2"}
            assert _publish(request).posted is posted
            assert statuses() == (HeadReviewState.COMPLETED, ReviewRequestOutcomeStatus.COMPLETED)
            if repair_completion:
                marker = ReviewReportArtefact.objects.for_team(self.team.id).get(
                    report_id=report_id, type=ReviewReportArtefact.ArtefactType.TURN_MARKER
                )
                content = TurnMarkerArtefact.model_validate_json(marker.content)
                marker.content = content.model_copy(update={"publication_completed_at": None}).model_dump_json()
                marker.save(update_fields=["content"])
                assert _publish(request).posted is False
            report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
            marker = ReviewReportArtefact.objects.for_team(self.team.id).get(
                report_id=report_id, type=ReviewReportArtefact.ArtefactType.TURN_MARKER
            )
            assert TurnMarkerArtefact.model_validate_json(marker.content).publication_completed_at is not None
            assert full_review_published(report) is (posted and request_id is None)
            assert (report.published_heads_by_mode or {}).get("flash") == "sha0"
            assert _publish(request).posted is False
            with patch(f"{_ACTIVITIES}.fail_status_comment"):
                _fail_run(self.team.id, report_id, run_index=2)
            assert _publish(request).posted is False
            assert statuses() == (HeadReviewState.FAILED, ReviewRequestOutcomeStatus.FAILED)

        posts = [call.kwargs["json"] for call in github.call_args_list if call.args[0] == "POST"]
        assert len(posts) == int(posted)
        if posts:
            assert _review_marker(report_id, "sha1", "full", "turn" if request_id else None) in posts[0]["body"]

    @parameterized.expand([("same_head", "sha1"), ("other_head", "sha2")])
    @patch(_AUTH, return_value=("tok", None))
    def test_reused_run_index_cannot_publish_another_turn(self, _name: str, head: str, _auth: MagicMock) -> None:
        report_id = self._report()
        for turn_id, marker_head in [("abandoned", "sha1"), ("replacement", head)]:
            ReviewReportArtefact.add_turn_marker(
                team_id=self.team.id,
                report_id=report_id,
                content=TurnMarkerArtefact(
                    head_sha=marker_head,
                    run_index=1,
                    review_mode="full",
                    reviewhog_version="test",
                    reviewhog_fingerprint="test",
                    stamphog_review_run_id="refusal",
                    queue_turn_id=turn_id,
                    publishes=True,
                ),
                attribution=ArtefactAttribution.system(),
            )
        with pytest.raises(ValueError, match="turn identity"):
            _publish(replace(_publish_input(self.team.id, report_id, "sha1"), queue_turn_id="abandoned"))
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert not report.published_head_shas

    def _report(self, *, published_head_sha: str | None = None) -> str:
        report_id = upsert_review_report(
            team_id=self.team.id,
            repository="PostHog/posthog",
            pr_url="https://github.com/PostHog/posthog/pull/1",
            pr_metadata=_pr_metadata("sha1"),
        )
        if published_head_sha is not None:
            ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(
                published_head_sha=published_head_sha
            )
        return report_id

    @parameterized.expand(
        [
            ("full_then_flash", "full", "flash", False, False),
            ("flash_then_full", "flash", "full", False, False),
            ("fallback_then_standard", "full", "flash", True, False),
            ("fallback_then_manual_deep", "full", "full", True, False),
            ("fallback_crash_then_manual_deep", "full", "full", True, True),
        ]
    )
    @patch(_AUTH, return_value=("tok", None))
    def test_distinct_modes_publish_once_each_at_the_same_head(
        self, _name: str, first_mode: str, second_mode: str, fallback: bool, crash: bool, _auth: MagicMock
    ) -> None:
        report_id = self._report()
        first = replace(
            _publish_input(self.team.id, report_id, "sha1"),
            review_mode=first_mode,
            queue_turn_id="fallback-turn" if fallback else None,
        )
        second = replace(first, review_mode=second_mode, run_index=2, queue_turn_id=None)
        for item in (first, second):
            ReviewReportArtefact.add_turn_marker(
                team_id=self.team.id,
                report_id=report_id,
                content=TurnMarkerArtefact(
                    head_sha=item.head_sha,
                    run_index=item.run_index,
                    review_mode=item.review_mode,
                    reviewhog_version="test",
                    reviewhog_fingerprint="test",
                    publishes=True,
                    queue_turn_id=item.queue_turn_id,
                    stamphog_review_run_id="refusal" if item.queue_turn_id else None,
                ),
                attribution=ArtefactAttribution.system(),
            )
            key = f"r{item.run_index}:guard"
            ReviewReportArtefact.append_finding(
                team_id=self.team.id,
                report_id=report_id,
                content=ReviewIssueFinding(
                    issue_key=key,
                    run_index=item.run_index,
                    title=f"Missing guard {item.run_index}",
                    file="handler.py",
                    body=f"Finding from turn {item.run_index}",
                    suggestion="Check the value first.",
                    priority=IssuePriority.SHOULD_FIX,
                ),
                attribution=ArtefactAttribution.system(),
            )
            ReviewReportArtefact.append_verdict(
                team_id=self.team.id,
                report_id=report_id,
                content=ValidationVerdict(issue_key=key, is_valid=True, argumentation="The value is unchecked."),
                attribution=ArtefactAttribution.system(),
            )
        reviews: list[dict[str, Any]] = []
        ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(report_markdown="Missing guard 1")

        def github_request(method: str, path: str, **kwargs: Any) -> MagicMock:
            if method == "POST":
                reviews.append({**kwargs["json"], "user": {"login": "posthog[bot]", "type": "Bot"}})
            return MagicMock(
                json=lambda: {"html_url": f"https://github.com/PostHog/posthog/pull/1#review-{len(reviews)}"}
            )

        with (
            patch(
                "products.review_hog.backend.reviewer.tools.publish_review.github_api_request",
                side_effect=github_request,
            ),
            patch(_PAGINATED, side_effect=lambda *args, **kwargs: iter(reviews)),
            patch("products.review_hog.backend.reviewer.tools.publish_review.remove_own_pr_reactions"),
        ):
            if crash:
                with patch.object(ReviewReport, "save", side_effect=RuntimeError("watermark unavailable")):
                    with pytest.raises(RuntimeError, match="watermark unavailable"):
                        _publish(first)
            for item in (first, second):
                ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(
                    report_markdown=f"Missing guard {item.run_index}"
                )
                _publish(item)
            for item in (first, second):
                _publish(item)
        assert len(reviews) == 2
        assert "Missing guard 1" in reviews[0]["body"]
        assert "Missing guard 2" in reviews[1]["body"]
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.published_heads_by_mode == (
            {second_mode: "sha1"} if fallback else {"full": "sha1", "flash": "sha1"}
        )

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_publication_write_keeps_a_watermark_that_landed_while_posting(
        self, _auth, _snapshot, mock_publish
    ) -> None:
        report_id = self._report()

        def post_while_the_other_mode_publishes(**_kwargs: Any) -> PublishOutcome:
            # The standalone publish command runs outside the per-PR queue, so a Flash publication
            # can commit while this Full one is still posting to GitHub.
            ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(
                published_heads_by_mode={"flash": "sha1"}, published_head_shas={"9": "sha1"}
            )
            return PublishOutcome(posted=True)

        mock_publish.side_effect = post_while_the_other_mode_publishes
        _publish(_publish_input(self.team.id, report_id, "sha1"))

        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.published_heads_by_mode == {"flash": "sha1", "full": "sha1"}
        assert report.published_head_shas == {"9": "sha1", "1": "sha1"}

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", "9876543"))
    def test_first_publish_records_watermark(self, _auth, _snapshot, mock_publish) -> None:
        mock_publish.return_value = PublishOutcome(posted=True)
        report_id = self._report()
        _publish(_publish_input(self.team.id, report_id, "sha1"))
        assert mock_publish.call_count == 1
        # The resolved installation id must reach the GitHub calls — dropping it silently turns the
        # publish identity-blind (no egress budget accounting).
        assert mock_publish.call_args.kwargs["installation_id"] == "9876543"
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.published_head_sha == "sha1"
        # The gating threshold is snapshotted with the watermark, keyed by the publishing turn —
        # outcome classification reconstructs the published set from it, so a later settings change
        # can't rewrite what was posted.
        assert report.published_urgency_thresholds == {"1": "should_fix"}
        # Publishing runs arrive here still ACTIVE (finalize defers the idle write); the posted
        # save must restore rest or the row reads as in-progress until the staleness cutoff.
        assert report.status == ReviewReport.Status.IDLE

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_a_review_says_when_the_finding_budget_left_findings_out(self, _auth, _snapshot, mock_publish) -> None:
        mock_publish.return_value = PublishOutcome(posted=True)
        report_id = self._report()
        cut = Issue(
            id="1-1-2", title="Cut", file="a.py", lines=[], issue="i", suggestion="", priority=IssuePriority.CONSIDER
        )
        replace_dropped_findings(
            team_id=self.team.id,
            report_id=report_id,
            run_index=1,
            head_sha="sha1",
            dropped=[
                DroppedIssue(issue=cut, disposition="budget", rank=2),
                DroppedIssue(issue=cut.model_copy(update={"id": "1-1-3"}), disposition="budget", rank=3),
                DroppedIssue(issue=cut.model_copy(update={"id": "1-1-4"}), disposition="cap", rank=4),
            ],
            cap=4,
            lens_part_count=1,
        )

        _publish(_publish_input(self.team.id, report_id, "sha1"))

        assert mock_publish.call_args.kwargs["budget_note"] == (
            "This pull request reached its limit of 20 automatic review findings, so this review left out "
            "2 lower-priority findings. Must-fix findings still post."
        )

    @parameterized.expand(
        [
            ("second_round_stays_quiet", {"1": "sha0"}, ""),
            (
                "third_round_asks_for_a_rethink",
                {"1": "sha0", "2": "sha0"},
                "This is review round 3 on this pull request.",
            ),
        ]
    )
    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_a_review_says_which_round_it_is_from_the_round_cap_on(
        self, _name, published_head_shas, expected_prefix, _auth, _snapshot, mock_publish
    ) -> None:
        mock_publish.return_value = PublishOutcome(posted=True)
        report_id = self._report()
        ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(published_head_shas=published_head_shas)

        _publish(replace(_publish_input(self.team.id, report_id, "sha1"), run_index=3))

        note = mock_publish.call_args.kwargs["round_note"]
        assert note[: len(expected_prefix)] == expected_prefix
        assert bool(note) is bool(expected_prefix)

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_republish_same_head_is_skipped(self, _auth, _snapshot, mock_publish) -> None:
        report_id = self._report(published_head_sha="sha1")
        _publish(_publish_input(self.team.id, report_id, "sha1"))
        mock_publish.assert_not_called()
        # The skip exit must also restore rest: an activity retry can land here with the report
        # still deferred-ACTIVE from finalize.
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).status == ReviewReport.Status.IDLE

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_new_head_publishes(self, _auth, _snapshot, mock_publish) -> None:
        mock_publish.return_value = PublishOutcome(posted=True)
        report_id = self._report(published_head_sha="oldsha")
        _publish(_publish_input(self.team.id, report_id, "sha2"))
        assert mock_publish.call_count == 1
        assert ReviewReport.objects.for_team(self.team.id).get(id=report_id).published_head_sha == "sha2"

    @parameterized.expand(
        [
            ("automatic_draft_with_commands", "automatic", True, True, "Comment `@posthog review` to review", False),
            (
                "automatic_draft_without_commands",
                "automatic",
                True,
                False,
                "Start a review in PostHog Review to",
                False,
            ),
            ("automatic_ready", "automatic", False, True, None, False),
            # A Stamphog handoff also runs for authors without automatic reviews, so it cannot promise one on ready.
            ("stamphog_draft", "stamphog", True, True, None, True),
            ("comment_ready", "comment", False, True, None, True),
            ("ui_ready", "ui", False, True, None, True),
            ("inbox_ready", "inbox", False, True, None, False),
        ]
    )
    @patch(_PUBLISH)
    @patch(_AUTH, return_value=("tok", None))
    def test_the_publish_notes_follow_the_trigger(
        self,
        _name: str,
        trigger_source: str,
        draft: bool,
        commands_on: bool,
        expected_trigger: str | None,
        expects_reply: bool,
        _auth,
        mock_publish,
    ) -> None:
        mock_publish.return_value = PublishOutcome(posted=True)
        report_id = self._report()
        snapshot = PRSnapshotArtefact(
            head_sha="sha1",
            pr_metadata=_pr_metadata("sha1").model_copy(update={"draft": draft}),
            pr_comments=[],
            pr_files=[],
        )
        with (
            patch(_SNAPSHOT, return_value=snapshot),
            patch(f"{_ACTIVITIES}.comment_commands_enabled", return_value=commands_on),
        ):
            _publish(replace(_publish_input(self.team.id, report_id, "sha1"), trigger_source=trigger_source))

        assert mock_publish.call_args.kwargs["answers_request"] is expects_reply
        findings_footer = mock_publish.call_args.kwargs["findings_footer"]
        if expected_trigger is None:
            assert findings_footer == ""
        else:
            assert findings_footer.startswith("This is the only automatic review while this pull request is a draft.")
            assert expected_trigger in findings_footer

    @patch(_PUBLISH)
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_noop_publish_does_not_record_watermark(self, _auth, _snapshot, mock_publish) -> None:
        # Nothing publishable (validator dropped everything): the head must NOT be watermarked, so a
        # later turn with a valid finding can still publish at the same head.
        mock_publish.return_value = PublishOutcome(posted=False)
        report_id = self._report()
        _publish(replace(_publish_input(self.team.id, report_id, "sha1"), trigger_source="automatic"))
        assert mock_publish.call_count == 1
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.published_head_sha is None
        assert report.automatic_reviewed_head_sha == "sha1"
        # No watermark, but the turn is over: the no-post exit still restores rest.
        assert report.status == ReviewReport.Status.IDLE

    @patch(_PUBLISH, side_effect=RuntimeError("GitHub unavailable"))
    @patch(_SNAPSHOT, return_value=None)
    @patch(_AUTH, return_value=("tok", None))
    def test_failed_publication_does_not_complete_an_automatic_review(self, _auth, _snapshot, _publish_mock) -> None:
        report_id = self._report()
        with self.assertRaises(RuntimeError):
            _publish(replace(_publish_input(self.team.id, report_id, "sha1"), trigger_source="automatic"))
        report = ReviewReport.objects.for_team(self.team.id).get(id=report_id)
        assert report.automatic_reviewed_head_sha is None


@pytest.mark.asyncio
async def test_publish_waits_for_the_rate_limit_reset_github_names() -> None:
    with (
        patch(f"{_ACTIVITIES}._publish", side_effect=GitHubRateLimitError("limited", retry_after=3000)),
        pytest.raises(ApplicationError) as raised,
    ):
        await ActivityEnvironment().run(publish_review_activity, _publish_input(1, "rep-1", "sha1"))

    assert raised.value.next_retry_delay == timedelta(seconds=3000)
