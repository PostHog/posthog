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
                "help_text": "Active primary team slug from OwnersResolver (e.g. 'team-replay'), "
                "or the literal 'unowned' for tests whose spans carry no ownership stamp.",
            },
            "has_test_activity": {
                "help_text": "True when this team has recent test-health evidence in either compared window."
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
                "help_text": "Runs where an owned test failed while quarantined (xfail): masked in CI, still failing.",
            },
            "quarantined_failed_run_count_prior": {"help_text": "Same count over the prior window."},
            "last_seen_at": {
                "help_text": "Most recent failure, in-job recovery, or xfail signal across the team's owned tests. "
                "A cross-attempt pass proves recovery but does not advance recency."
            },
        }


class TeamCIHealthListSerializer(DataclassSerializer):
    items = TeamCIHealthItemSerializer(
        many=True,
        help_text="Active primary code-owning teams, plus the unowned telemetry bucket when evidence exists. "
        "Teams with recent signals are ranked first; this never aggregates by author.",
    )

    class Meta:
        dataclass = TeamCIHealthList
        extra_kwargs = {
            "truncated": {"help_text": "True when more roster or telemetry rows qualified than the cap."},
            "limit": {"help_text": "Maximum number of teams returned in `items`."},
            "surface": {"help_text": "Requested test surface: all, backend, or frontend."},
            "has_ownership_catalog": {
                "help_text": "True when a recent CI-emitted OwnersResolver catalog was available for this repository."
            },
            "ownership_catalog_captured_at": {
                "help_text": "Capture time of the ownership catalog, or null when no recent catalog is available."
            },
        }


class TeamTestSignalSerializer(DataclassSerializer):
    class Meta:
        dataclass = TeamTestSignal
        extra_kwargs = {
            "nodeid": {"help_text": "Normalized test identity (the CI span name), a stable grouping key."},
            "selector": {"help_text": "Runnable framework-specific selector emitted by the CI reporter."},
            "surface": {"help_text": "Test surface that produced this signal: backend or frontend."},
            "signal_count": {
                "help_text": "Runs in the current window where the test failed, errored, or a retry "
                "recovered it (xfail excluded).",
            },
            "signal_count_prior": {"help_text": "Same count over the equal-length window before date_from."},
            "last_seen_at": {
                "help_text": "Most recent failure, in-job recovery, or xfail signal for this test. A cross-attempt "
                "pass proves recovery but does not advance recency."
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
            "surface": {"help_text": "Requested test surface: all, backend, or frontend."},
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
