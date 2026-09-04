from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.temporal.activities import FetchPRDataInput, _fetch_and_persist
from products.review_hog.backend.temporal.types import TRIGGER_INBOX
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
    @patch(f"{_MODULE}._installation_auth", return_value=("tok", "9876543"))
    @patch(f"{_MODULE}.PRFetcher")
    def test_inbox_fetch_routes_a_new_report_by_its_signal_reports_priority(self, mock_fetcher, _auth) -> None:
        # The tier is only as good as this wiring: a fetch that forgets to hand the trigger's
        # priority to the upsert routes every agent PR as unprioritized, which is silently xhigh.
        signal_report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.IN_PROGRESS, signal_count=1, total_weight=1.0
        )
        mock_fetcher.return_value.fetch_pr_data.return_value = (_pr_metadata(), [], [], "")

        with override_settings(REVIEWHOG_TEAM_IDS=[self.team.id]):
            meta = _fetch_and_persist(
                FetchPRDataInput(
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
            )

        row = ReviewReport.objects.for_team(self.team.id).get(id=meta.report_id)
        assert (row.review_tier, row.review_signal_priority, row.review_reasoning_effort) == (
            "agent_p3_p4",
            "P3",
            "low",
        )
