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
                "help_text": "Owned tests one commit was seen both failing and passing in the window: the same "
                "proof, and the same word, that flaky_tests calls a confirmed_flake. Compare with "
                "flaky_test_count_prior for the delta.",
            },
            "flaky_test_count_prior": {
                "help_text": "Same count over the equal-length window immediately before date_from.",
            },
            "regression_test_count": {
                "help_text": "Owned tests that failed with no recorded same-commit recovery and still hit the "
                "blast-radius bar (a master/main failure, or min_failed_prs distinct PRs). Not flakes: absence "
                "of proof, not proof.",
            },
            "regression_test_count_prior": {"help_text": "Same count over the prior window."},
            "failed_run_count": {
                "help_text": "CI runs (not spans) where an owned test's recorded outcome was failed or error. "
                "An absolute count, not a rate: fast passing runs are not emitted.",
            },
            "failed_run_count_prior": {"help_text": "Same count over the prior window."},
            "same_commit_recovery_run_count": {
                "help_text": "Runs where one commit both failed and passed an owned test: a re-run attempt went "
                "green, or an in-job retry recovered it.",
            },
            "same_commit_recovery_run_count_prior": {"help_text": "Same count over the prior window."},
            "quarantined_failed_run_count": {
                "help_text": "Runs where an owned test recorded a tolerated failure while quarantined: masked in "
                "CI, still failing.",
            },
            "quarantined_failed_run_count_prior": {"help_text": "Same count over the prior window."},
            "last_seen_at": {
                "help_text": "Most recent failure, recovery, or quarantined-failure run across the team's owned "
                "tests, either window."
            },
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
            "runner": {"help_text": "Test runner that emitted this signal: 'pytest' or 'jest'."},
            "nodeid": {"help_text": "Runner-specific test identity (the CI span name), a stable grouping key."},
            "selector": {"help_text": "Runnable pytest or Jest selector; exact for newly emitted spans."},
            "signal_count": {
                "help_text": "Runs in the current window where the test failed, errored, or a retry "
                "recovered it (quarantined failures excluded).",
            },
            "signal_count_prior": {"help_text": "Same count over the equal-length window before date_from."},
            "last_seen_at": {
                "help_text": "Most recent failure, recovery, or quarantined-failure run for this test, either window."
            },
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
