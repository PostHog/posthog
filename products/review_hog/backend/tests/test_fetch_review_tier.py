from dataclasses import replace

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import DEFAULT_REVIEW_ARM, REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.persistence import load_pr_snapshot, load_review_arm
from products.review_hog.backend.reviewer.tools.github_meta import FetchedPR
from products.review_hog.backend.temporal.activities import FetchPRDataInput, _fetch_and_persist
from products.review_hog.backend.temporal.types import TRIGGER_INBOX, TRIGGER_UI
from products.signals.backend.models import SignalReport

_MODULE = "products.review_hog.backend.temporal.activities"


def _pr_metadata() -> PRMetadata:
    return PRMetadata(
        number=9,
        title="t",
        state="open",
        draft=False,
        created_at="",
        updated_at="",
        author="posthog[bot]",
        base_branch="main",
        head_branch="posthog-code/fix",
        head_sha="sha1",
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


class TestFetchDecidesTheTier(BaseTest):
    @parameterized.expand(
        [
            (None, "open", [], False, False),
            # A ready_for_review turn after the draft's automatic review at the same head.
            ("sha1", "open", [], True, False),
            (None, "closed", [], False, False),
            # `gh pr create --label` adds the label after the `opened` delivery.
            (None, "open", ["Skip-Agent-Review"], False, True),
        ]
    )
    @patch(f"{_MODULE}._installation_auth", return_value=("tok", None))
    @patch(f"{_MODULE}.PRFetcher")
    def test_automatic_completion_requires_a_successful_publication_step(
        self,
        automatic_head: str | None,
        state: str,
        labels: list[str],
        complete: bool,
        skipped: bool,
        mock_fetcher: MagicMock,
        _auth: MagicMock,
    ) -> None:
        metadata = _pr_metadata().model_copy(update={"state": state, "labels": labels})
        mock_fetcher.return_value.fetch_pr_data.return_value = FetchedPR(
            pr_metadata=metadata, pr_comments=[], pr_files=[], diff=""
        )
        request = FetchPRDataInput(
            team_id=self.team.id,
            user_id=self.user.id,
            repository="o/r",
            owner="o",
            repo="r",
            pr_number=9,
            review_mode="flash",
            trigger_source="automatic",
        )
        first = _fetch_and_persist(request)
        report = ReviewReport.objects.for_team(self.team.id).get(id=first.report_id)
        report.completed_head_sha = "sha1"
        report.automatic_reviewed_head_sha = automatic_head
        report.save()

        meta = _fetch_and_persist(request)
        report.refresh_from_db()

        assert meta.already_completed is complete
        assert meta.pr_open is (state == "open")
        assert meta.automatic_reviewed_head_sha == automatic_head
        assert meta.skip_agent_review is skipped
        expected_status = "closed" if state == "closed" else "idle" if complete or skipped else "active"
        assert report.status == expected_status

    @parameterized.expand(
        [
            ("flash", REVIEW_MODE_FLASH, [10], 1, True),
            ("flash_two_parts", REVIEW_MODE_FLASH, [600, 600], 2, True),
            ("full", REVIEW_MODE_FULL, [10], 0, False),
        ]
    )
    @patch(f"{_MODULE}.standard_coordinator_on", return_value=True)
    @patch(f"{_MODULE}.flash_pipeline_kill_switch_on", return_value=False)
    @patch(f"{_MODULE}._installation_auth", return_value=("tok", None))
    @patch(f"{_MODULE}.PRFetcher")
    def test_fetch_records_the_lens_parts_of_a_single_agent_turn(
        self,
        _name: str,
        review_mode: str,
        additions: list[int],
        expected_parts: int,
        expected_coordinator: bool,
        mock_fetcher: MagicMock,
        _auth: MagicMock,
        _kill_switch: MagicMock,
        _coordinator: MagicMock,
    ) -> None:
        # The workflow fans the lens sessions out over this count, so a fetch that leaves it at the
        # default runs every Flash turn without its lenses and no error shows it. Only the
        # single-agent design fetches test and `.txt` files, so the design must be known first.
        # Its prompt reads a left-out diff against the merge base, so the snapshot must keep it.
        pr_files = [
            PRFile(filename=f"d{index}/a.py", status="modified", additions=count, deletions=0)
            for index, count in enumerate(additions)
        ]
        merge_base_sha = "f" * 40
        mock_fetcher.return_value.fetch_pr_data.return_value = FetchedPR(
            pr_metadata=_pr_metadata(), pr_comments=[], pr_files=pr_files, diff="", merge_base_sha=merge_base_sha
        )
        meta = _fetch_and_persist(
            FetchPRDataInput(
                team_id=self.team.id,
                user_id=self.user.id,
                repository="o/r",
                owner="o",
                repo="r",
                pr_number=9,
                review_mode=review_mode,
            )
        )

        assert meta.lens_chunk_count == expected_parts
        assert meta.coordinator is expected_coordinator
        single_agent = review_mode == REVIEW_MODE_FLASH
        assert mock_fetcher.return_value.fetch_pr_data.call_args.kwargs == {
            "review_tests_and_text": single_agent,
            "with_merge_base": True,
        }
        snapshot = load_pr_snapshot(team_id=self.team.id, report_id=meta.report_id, head_sha=meta.head_sha)
        assert snapshot is not None and snapshot.merge_base_sha == merge_base_sha

    @patch(f"{_MODULE}._installation_auth", return_value=("tok", "9876543"))
    @patch(f"{_MODULE}.PRFetcher")
    def test_fetch_keeps_the_created_tier_until_a_full_human_review(
        self, mock_fetcher: MagicMock, _auth: MagicMock
    ) -> None:
        # The tier is only as good as this wiring: a fetch that forgets to hand the trigger's
        # priority to the upsert routes every agent PR as unprioritized, which is silently xhigh.
        signal_report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.IN_PROGRESS, signal_count=1, total_weight=1.0
        )
        mock_fetcher.return_value.fetch_pr_data.return_value = FetchedPR(
            pr_metadata=_pr_metadata(), pr_comments=[], pr_files=[], diff=""
        )

        fetch_input = FetchPRDataInput(
            team_id=self.team.id,
            user_id=1,
            repository="o/r",
            owner="o",
            repo="r",
            pr_number=9,
            pr_url="https://github.com/o/r/pull/9",
            signal_report_id=str(signal_report.id),
            trigger_source=TRIGGER_INBOX,
            signal_priority="P3",
        )
        meta = _fetch_and_persist(fetch_input)

        row = ReviewReport.objects.for_team(self.team.id).get(id=meta.report_id)
        assert (row.review_tier, row.review_signal_priority, row.review_reasoning_effort) == (
            "agent_p3_p4",
            "P3",
            "low",
        )
        original_arm = load_review_arm(team_id=self.team.id, report_id=meta.report_id)

        _fetch_and_persist(replace(fetch_input, trigger_source=TRIGGER_UI, review_mode=REVIEW_MODE_FLASH))
        row.refresh_from_db()
        assert (row.review_tier, row.review_signal_priority, row.review_reasoning_effort) == (
            "agent_p3_p4",
            "P3",
            "low",
        )
        assert load_review_arm(team_id=self.team.id, report_id=meta.report_id) == original_arm

        _fetch_and_persist(replace(fetch_input, trigger_source=TRIGGER_UI))
        row.refresh_from_db()
        assert (row.review_tier, row.review_signal_priority, row.review_reasoning_effort) == (
            "human",
            "P3",
            "xhigh",
        )
        assert load_review_arm(team_id=self.team.id, report_id=meta.report_id) == DEFAULT_REVIEW_ARM
