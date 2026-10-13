import re

from django.test import SimpleTestCase

from parameterized import parameterized

from products.product_analytics.backend.facade.enums import (
    InsightDataCheckAction,
    InsightDataCheckKey,
    InsightDataCheckLevel,
)
from products.product_analytics.backend.insight_data_checks import (
    DataCheckCounts,
    InternalUserCounts,
    evaluate_data_checks,
    own_team_email_pattern,
)

PASSED = InsightDataCheckLevel.PASSED
WARNING = InsightDataCheckLevel.WARNING
PROBLEM = InsightDataCheckLevel.PROBLEM
SKIPPED = InsightDataCheckLevel.SKIPPED


def counts(
    events: int,
    *,
    internal: int = 0,
    missed_by_filter: int = 0,
    internal_is_sample: bool = False,
    local: int = 0,
    bots: int = 0,
    duplicates: int = 0,
    sample_rate: float = 1.0,
) -> DataCheckCounts:
    return DataCheckCounts(
        events=events,
        local_events=local,
        bot_events=bots,
        distinct_events=events - duplicates,
        internal_users=InternalUserCounts(
            events=events, removed_by_filter=internal, missed_by_filter=missed_by_filter, is_sample=internal_is_sample
        ),
        sample_rate=sample_rate,
    )


class TestEvaluateDataChecks(SimpleTestCase):
    @parameterized.expand(
        [
            ("internal_fifth_is_a_problem", InsightDataCheckKey.INTERNAL_USERS, counts(1000, internal=200), PROBLEM),
            (
                "internal_small_share_is_a_warning",
                InsightDataCheckKey.INTERNAL_USERS,
                counts(1000, internal=60),
                WARNING,
            ),
            ("internal_under_50_events", InsightDataCheckKey.INTERNAL_USERS, counts(1000, internal=49), PASSED),
            ("internal_under_two_percent", InsightDataCheckKey.INTERNAL_USERS, counts(100000, internal=1900), PASSED),
            ("internal_over_two_percent", InsightDataCheckKey.INTERNAL_USERS, counts(100000, internal=2100), WARNING),
            (
                "local_tiny_share_still_counts",
                InsightDataCheckKey.LOCAL_DEVELOPMENT,
                counts(1000000, local=60),
                WARNING,
            ),
            ("local_under_50_events", InsightDataCheckKey.LOCAL_DEVELOPMENT, counts(100, local=49), PASSED),
            ("local_fifth_is_a_problem", InsightDataCheckKey.LOCAL_DEVELOPMENT, counts(1000, local=200), PROBLEM),
            ("bots_small_share_is_a_warning", InsightDataCheckKey.BOT_TRAFFIC, counts(10000, bots=200), WARNING),
            ("bots_under_one_percent", InsightDataCheckKey.BOT_TRAFFIC, counts(100000, bots=500), PASSED),
            ("duplicates_under_100_events", InsightDataCheckKey.DUPLICATE_EVENTS, counts(1000, duplicates=99), PASSED),
            (
                "duplicates_under_five_percent",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(10000, duplicates=400),
                PASSED,
            ),
            (
                "duplicates_over_both_floors",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(10000, duplicates=600),
                WARNING,
            ),
            (
                "duplicates_fifth_is_a_problem",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(1000, duplicates=250),
                PROBLEM,
            ),
        ]
    )
    def test_level_follows_count_and_share(
        self, _name: str, key: InsightDataCheckKey, check_counts: DataCheckCounts, expected: InsightDataCheckLevel
    ) -> None:
        checks = evaluate_data_checks(check_counts, filters_internal_users=False, has_internal_users_filter=True)
        levels = {check.key: check.level for check in checks}
        assert levels[key] == expected
        assert all(level == PASSED for other, level in levels.items() if other != key)

    @parameterized.expand(
        [
            ("insight_filters_them_out", True, True, 0, 0, PASSED, None),
            ("project_has_no_filter", False, False, 0, 0, SKIPPED, InsightDataCheckAction.OPEN_FILTER_SETTINGS),
            (
                "the_filter_would_remove_them",
                False,
                True,
                300,
                0,
                PROBLEM,
                InsightDataCheckAction.FILTER_INTERNAL_USERS,
            ),
            (
                "the_filter_would_not_remove_enough_of_them",
                False,
                True,
                300,
                300,
                PROBLEM,
                InsightDataCheckAction.OPEN_FILTER_SETTINGS,
            ),
            (
                "left_by_the_filter_the_insight_applies",
                True,
                True,
                0,
                300,
                PROBLEM,
                InsightDataCheckAction.OPEN_FILTER_SETTINGS,
            ),
            (
                "found_without_a_project_filter",
                False,
                False,
                0,
                300,
                PROBLEM,
                InsightDataCheckAction.OPEN_FILTER_SETTINGS,
            ),
        ]
    )
    def test_internal_users_check_depends_on_the_filters_in_place(
        self,
        _name: str,
        filters_internal_users: bool,
        has_internal_users_filter: bool,
        removed_by_filter: int,
        missed_by_filter: int,
        expected_level: InsightDataCheckLevel,
        expected_action: InsightDataCheckAction | None,
    ) -> None:
        checks = evaluate_data_checks(
            counts(1000, internal=removed_by_filter, missed_by_filter=missed_by_filter),
            filters_internal_users=filters_internal_users,
            has_internal_users_filter=has_internal_users_filter,
        )
        check = next(check for check in checks if check.key == InsightDataCheckKey.INTERNAL_USERS)
        assert (check.level, check.action) == (expected_level, expected_action)

    @parameterized.expand(
        [
            ("every_event_read", 1.0, "66 of these events came from local development"),
            ("sample_read", 0.01, "About 6,600 of these events came from local development"),
        ]
    )
    def test_a_count_from_a_sample_is_scaled_up_to_the_whole_insight(
        self, _name: str, sample_rate: float, expected: str
    ) -> None:
        checks = evaluate_data_checks(
            counts(1000000, local=66, sample_rate=sample_rate),
            filters_internal_users=False,
            has_internal_users_filter=True,
        )
        check = next(check for check in checks if check.key == InsightDataCheckKey.LOCAL_DEVELOPMENT)
        assert check.result == expected

    @parameterized.expand(
        [
            ("every_event_read", False, "30% of these events came from internal and test users"),
            ("sample_of_people_read", True, "About 30% of these events came from internal and test users"),
        ]
    )
    def test_an_internal_users_share_from_a_sample_is_stated_as_an_estimate(
        self, _name: str, is_sample: bool, expected: str
    ) -> None:
        checks = evaluate_data_checks(
            counts(1000, internal=300, internal_is_sample=is_sample),
            filters_internal_users=False,
            has_internal_users_filter=True,
        )
        assert checks[0].result == expected

    def test_a_finding_states_its_share_and_carries_the_numbers(self) -> None:
        checks = evaluate_data_checks(
            counts(21336, internal=4661), filters_internal_users=False, has_internal_users_filter=True
        )
        check = checks[0]
        assert check.result == "22% of these events came from internal and test users"
        assert check.events == 4661
        assert check.share is not None and round(check.share, 3) == 0.218

    @parameterized.expand(
        [
            ("company_domain", "sam@acme.example", True),
            ("subdomain_of_the_company_domain", "sam@eu.acme.example", True),
            ("member_on_a_public_provider", "founder@gmail.com", True),
            ("test_account", "test@gmail.com", True),
            ("numbered_test_account", "qa2@shop.example", True),
            ("test_alias", "maria+test1@shop.example", True),
            ("longer_domain_that_starts_the_same", "sam@acme.example.br", False),
            ("domain_that_ends_the_same", "sam@notacme.example", False),
            ("another_person_on_the_public_provider", "afounder@gmail.com", False),
            ("word_that_starts_with_test", "tester@shop.example", False),
            ("word_that_contains_test", "contest@shop.example", False),
            ("word_that_starts_with_demo", "demographics@shop.example", False),
            ("alias_that_is_not_a_test_word", "maria+news@shop.example", False),
        ]
    )
    def test_own_team_pattern_matches_the_team_and_test_accounts_only(
        self, _name: str, email: str, expected: bool
    ) -> None:
        pattern = own_team_email_pattern(("acme.example",), ("founder@gmail.com",))
        assert bool(re.search(pattern, email)) is expected
