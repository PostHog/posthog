from dataclasses import replace

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import DEFAULT_REVIEW_ARM, REVIEW_MODE_FLASH
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.persistence import load_review_arm
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
    @parameterized.expand([(None, "open", False), ("sha1", "open", True), (None, "closed", False)])
    @patch(f"{_MODULE}._installation_auth", return_value=("tok", None))
    @patch(f"{_MODULE}.PRFetcher")
    def test_automatic_completion_requires_a_successful_publication_step(
        self, automatic_head: str | None, state: str, complete: bool, mock_fetcher: MagicMock, _auth: MagicMock
    ) -> None:
        metadata = _pr_metadata().model_copy(update={"state": state})
        mock_fetcher.return_value.fetch_pr_data.return_value = (metadata, [], [], "")
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
        expected_status = "closed" if state == "closed" else "idle" if complete else "active"
        assert report.status == expected_status

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
        mock_fetcher.return_value.fetch_pr_data.return_value = (_pr_metadata(), [], [], "")

        with override_settings(REVIEWHOG_TEAM_IDS=[self.team.id]):
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
