"""Payloads for team-level rollups: CI health, activity, and merge trend."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    TeamCIActivity,
    TeamCIHealthItem,
    TeamCIHealthList,
    TeamMergeTrend,
    TeamMergeTrendPoint,
    TeamTestSignal,
)


class TeamCIHealthItemSerializer(DataclassSerializer):
    class Meta:
        dataclass = TeamCIHealthItem
        extra_kwargs = {
            "owner_team": {
                "help_text": "Owning team slug (the CODEOWNERS handle minus '@PostHog/', e.g. 'team-replay'), "
                "or the literal 'unowned' for tests whose spans carry no ownership stamp.",
            },
            "flaky_test_count": {
                "help_text": "Owned tests meeting the flaky-leaderboard bar in the window (passed on retry "
                "or failed on enough distinct PRs). Compare with flaky_test_count_prior for the delta.",
            },
            "flaky_test_count_prior": {
                "help_text": "Same count over the equal-length window immediately before date_from.",
            },
            "failed_count": {
                "help_text": "Signal spans on owned tests with final outcome 'failed' or 'error' in the "
                "window. An absolute count, not a rate: fast passing runs are not emitted.",
            },
            "failed_count_prior": {"help_text": "Same count over the prior window."},
            "rerun_passed_count": {
                "help_text": "Spans on owned tests that failed, then passed on an automatic retry, the "
                "strongest flaky signal. Only rerun-enabled CI lanes emit it.",
            },
            "rerun_passed_count_prior": {"help_text": "Same count over the prior window."},
            "xfailed_count": {
                "help_text": "Spans on owned tests that failed while quarantined (xfail): masked in CI "
                "but still flaky.",
            },
            "xfailed_count_prior": {"help_text": "Same count over the prior window."},
            "last_seen_at": {"help_text": "Most recent signal span across the team's owned tests, either window."},
        }


class TeamCIHealthListSerializer(DataclassSerializer):
    items = TeamCIHealthItemSerializer(
        many=True,
        help_text="Owning teams ranked by current flaky + failure signal, heaviest first, capped at `limit`. "
        "Teams are organizational owners of code surfaces; this never aggregates by author.",
    )

    class Meta:
        dataclass = TeamCIHealthList
        extra_kwargs = {
            "truncated": {"help_text": "True when more teams had signal than the cap."},
            "limit": {"help_text": "Maximum number of teams returned in `items`."},
        }


class TeamTestSignalSerializer(DataclassSerializer):
    class Meta:
        dataclass = TeamTestSignal
        extra_kwargs = {
            "nodeid": {"help_text": "Reconstructed pytest nodeid (the CI span name), a stable grouping key."},
            "selector": {"help_text": "Runnable pytest selector; exact when the CI reporter emitted it."},
            "signal_count": {
                "help_text": "Failed + error + pass-on-retry spans in the current window (xfail excluded).",
            },
            "signal_count_prior": {"help_text": "Same count over the equal-length window before date_from."},
            "last_seen_at": {"help_text": "Most recent signal span for this test, either window."},
        }


class TeamCIActivitySerializer(DataclassSerializer):
    tests = TeamTestSignalSerializer(
        many=True,
        help_text="The team's owned tests with signal in either window, ranked by the stronger window's count "
        "(the current-vs-prior pairs behind a before/after comparison).",
    )

    class Meta:
        dataclass = TeamCIActivity
        extra_kwargs = {
            "owner_team": {"help_text": "The team slug this activity is scoped to, or 'unowned'."},
            "truncated_tests": {"help_text": "True when more owned tests had signal than the test cap."},
        }


class TeamMergeTrendPointSerializer(DataclassSerializer):
    class Meta:
        dataclass = TeamMergeTrendPoint
        extra_kwargs = {
            "day": {"help_text": "Start of the day bucket (team timezone), keyed on merged_at."},
            "median_seconds": {
                "help_text": "Median open→merge seconds of the PRs this team's members merged that day; "
                "null on a day the team merged nothing.",
            },
            "average_seconds": {
                "help_text": "Average open→merge seconds over the same merges; diverges above the median "
                "when a few long-running PRs drag the mean. Null on a day the team merged nothing.",
            },
            "merged_count": {"help_text": "Merged PRs behind that day's median and average."},
        }


class TeamMergeTrendSerializer(DataclassSerializer):
    points = TeamMergeTrendPointSerializer(
        many=True,
        help_text="Daily median and average open→merge over the PRs this team's members merged, ascending "
        "by day. Coarse timing (open→merge combines draft and review time); bots excluded.",
    )

    class Meta:
        dataclass = TeamMergeTrend
        extra_kwargs = {
            "owner_team": {"help_text": "The team slug this trend is scoped to."},
            "has_membership_data": {
                "help_text": "False when the GitHub source has no team_members snapshot synced: the trend "
                "then has no honest team attribution and `points` is empty.",
            },
        }
