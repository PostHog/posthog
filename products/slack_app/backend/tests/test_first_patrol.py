from unittest.mock import patch

from products.signals.backend.facade.api import ScoutRunDigest
from products.slack_app.backend import first_patrol

COLLECT_PATH = "products.signals.backend.facade.api.collect_scout_run_digests"


def _collect(digests):
    with patch(COLLECT_PATH, return_value=digests):
        return first_patrol.collect_first_patrol_digest(
            team_id=1, channel_name="posthog-inbox", scout_config_ids=["c1"], provisioned_at_iso="2026-07-02T00:00:00"
        )


class TestFirstPatrolDigestComposition:
    def test_no_completed_runs_returns_none_for_retry(self):
        assert _collect(None) is None

    def test_finding_variant_leads_with_the_finding_and_links_channel(self):
        digest = _collect(
            [
                ScoutRunDigest(
                    skill_name="signals-scout-csm-account-pulse",
                    summary="Initech's weekly active users dropped 60% vs baseline. Fleet otherwise steady.",
                    notifications_sent=1,
                    reports_filed=1,
                ),
                ScoutRunDigest(
                    skill_name="signals-scout-csm-support-watch",
                    summary="Queue quiet.",
                    notifications_sent=0,
                    reports_filed=0,
                ),
            ]
        )
        assert digest["variant"] == "finding"
        assert "Account pulse" in digest["text"]
        assert "Initech's weekly active users dropped 60% vs baseline." in digest["text"]
        assert "#posthog-inbox" in digest["text"]
        assert digest["runs_completed"] == 2

    def test_all_clear_variant_quotes_run_summaries_with_fallback(self):
        digest = _collect(
            [
                ScoutRunDigest(
                    skill_name="signals-scout-csm-account-pulse",
                    summary="Checked 214 accounts, all within baseline.",
                    notifications_sent=0,
                    reports_filed=0,
                ),
                ScoutRunDigest(
                    skill_name="signals-scout-csm-revenue-watch", summary="", notifications_sent=0, reports_filed=0
                ),
            ]
        )
        assert digest["variant"] == "all_clear"
        assert "Account pulse: Checked 214 accounts, all within baseline" in digest["text"]
        assert "Renewal & billing watch: checked in clean" in digest["text"]
        assert "Nothing to worry about right now" in digest["text"]

    def test_multiple_finders_counted_beyond_the_headline(self):
        digest = _collect(
            [
                ScoutRunDigest(
                    skill_name="signals-scout-csm-account-pulse",
                    summary="A slid.",
                    notifications_sent=1,
                    reports_filed=1,
                ),
                ScoutRunDigest(
                    skill_name="signals-scout-csm-support-watch",
                    summary="B spiked.",
                    notifications_sent=1,
                    reports_filed=1,
                ),
            ]
        )
        assert digest["variant"] == "finding"
        assert "1 more scout reported findings too" in digest["text"]
