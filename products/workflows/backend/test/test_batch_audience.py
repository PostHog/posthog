from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.redis import get_client as get_redis_client

from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillTrigger
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.dependencies import cohort_backfill_pending_key
from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.feature_flags.backend.person_sampling import bounded_memory_settings
from products.workflows.backend.services.batch_audience import get_batch_audience_person_ids_snapshot
from products.workflows.backend.services.blast_radius import AudienceCountInProgress, get_audience_size

FILTERS = {"properties": [{"key": "subscribed", "type": "person", "value": ["true"], "operator": "exact"}]}
_ON = datetime(2026, 1, 1, tzinfo=UTC)


def _uuid(index: int) -> str:
    # Only the last digit differs, so string ordering and ClickHouse UUID ordering agree.
    return f"01970000-0000-0000-0000-00000000000{index}"


class TestBatchAudience(ClickhouseTestMixin, BaseTest):
    def _create_audience(self, emails: list[str | None]) -> list[str]:
        person_ids = []
        for i, email in enumerate(emails, start=1):
            properties: dict = {"subscribed": "true"}
            if email is not None:
                properties["email"] = email
            _create_person(team=self.team, distinct_ids=[f"user-{i}"], uuid=_uuid(i), properties=properties)
            person_ids.append(_uuid(i))
        flush_persons_and_events()
        return person_ids

    @parameterized.expand(
        [
            # Duplicate emails (case/whitespace variants) collapse to the smallest UUID;
            # persons without an email (missing or empty) each keep their own entry.
            ("email_dedupe", "email", 10, [1, 3, 4, 5]),
            ("no_dedupe", None, 10, [1, 2, 3, 4, 5]),
            # The cap cuts the audience in id order, so the resolver's truncation sees the same first persons.
            ("capped", None, 2, [1, 2]),
        ]
    )
    def test_snapshot_query_returns_the_whole_audience_in_id_order(self, _name, dedupe_key, limit, expected_indices):
        self._create_audience(["Dup@X.com", " dup@x.com ", "b@x.com", None, ""])

        result = get_batch_audience_person_ids_snapshot(
            self.team, FILTERS, dedupe_key=dedupe_key, limit=limit, settings=bounded_memory_settings()
        )

        assert result == [_uuid(i) for i in expected_indices]

    def test_test_account_filters_that_only_apply_to_events_are_left_out(self):
        self.team.test_account_filters = [
            {"key": "$host", "type": "event", "value": "localhost", "operator": "is_not"},
            {"key": "email", "type": "person", "value": "@internal.example.com", "operator": "not_icontains"},
        ]
        self.team.save()
        self._create_audience(["a@example.com", "b@internal.example.com", "c@example.com"])
        filters = {**FILTERS, "filter_test_accounts": True}

        snapshot = get_batch_audience_person_ids_snapshot(
            self.team, filters, dedupe_key=None, limit=10, settings=bounded_memory_settings()
        )
        preview = get_audience_size(
            team_id=self.team.pk, filters=filters, group_type_index=None, dedupe_key=None, sends_email=False
        )

        assert snapshot == [_uuid(1), _uuid(3)]
        assert preview.affected == 2
        assert preview.skipped_test_account_filters == ["$host"]

    @parameterized.expand(
        [
            (f"{name}_{dedupe_key}", sql, dedupe_key)
            for name, sql in [
                ("person_id", f"person_id != '{_uuid(2)}'"),
                ("person_field", f"person.id != '{_uuid(2)}'"),
                ("person_property", "not ifNull(person.properties.email ILIKE '%@internal.example.com', 0)"),
                # The person without an email stays, because a missing value does not match the pattern.
                ("person_property_regex", "person.properties.email !~* '@INTERNAL[.]'"),
                ("after_non_ascii_text", f"'é😀' != 'x' and person_id != '{_uuid(2)}'"),
                ("beside_a_lambda", f"arrayExists(person_id -> person_id = 1, [1]) and person_id != '{_uuid(2)}'"),
                (
                    "person_id_of_a_subquery_stays_its_own",
                    f"person_id NOT IN (SELECT person_id FROM person_distinct_ids WHERE person_id = '{_uuid(2)}')",
                ),
            ]
            for dedupe_key in (None, "email")
        ]
    )
    def test_sql_test_account_filters_on_the_person_apply(self, _name, sql, dedupe_key):
        self.team.test_account_filters = [{"key": sql, "type": "hogql"}]
        self.team.save()
        self._create_audience(["a@example.com", "b@internal.example.com", None])
        filters = {**FILTERS, "filter_test_accounts": True}

        snapshot = get_batch_audience_person_ids_snapshot(
            self.team, filters, dedupe_key=dedupe_key, limit=10, settings=bounded_memory_settings()
        )
        preview = get_audience_size(
            team_id=self.team.pk, filters=filters, group_type_index=None, dedupe_key=dedupe_key, sends_email=False
        )

        assert snapshot == [_uuid(1), _uuid(3)]
        assert preview.affected == 2

    @parameterized.expand(
        [
            ("invalid_regex", {"key": "email", "type": "person", "value": "(@internal", "operator": "not_regex"}),
            ("missing_cohort", {"key": "id", "type": "cohort", "value": 999999999, "operator": "not_in"}),
            ("event_column_in_sql", {"key": "distinct_id != 'user-1'", "type": "hogql"}),
        ]
    )
    def test_a_person_test_account_filter_that_cannot_be_evaluated_fails_the_run(self, _name, test_filter):
        self.team.test_account_filters = [test_filter]
        self.team.save()
        self._create_audience(["a@example.com"])

        with self.assertRaises(ValidationError):
            get_batch_audience_person_ids_snapshot(
                self.team,
                {**FILTERS, "filter_test_accounts": True},
                dedupe_key=None,
                limit=10,
                settings=bounded_memory_settings(),
            )

    @parameterized.expand(
        [
            ("build_queued", "behavioral", "all", True, "building"),
            ("nothing_building", "behavioral", "all", False, "needs_attention"),
            # The pipeline doesn't run for the team, so the cohort never finishes calculating.
            ("team_off_realtime_allowlist", "behavioral", "none", True, "needs_attention"),
            # A load-test team runs the pipeline, but its users must not see the audience start building.
            (
                "team_granted_processing_only",
                "behavioral",
                "none",
                True,
                "needs_attention",
                RealtimeCohortLevel.PROCESSING,
            ),
            # The cohorts product reports this one as person_properties, which the response doesn't declare.
            ("person_property_cohort_on_a_behavioral_cohort", "person_on_behavioral", "all", False, "building"),
            # A stale debounce key must not make a cohort nobody turned on read as building.
            ("realtime_off", "behavioral", "all", True, "needs_attention", None, None),
        ]
    )
    def test_realtime_cohort_audience_size_estimates_from_the_cohort_count(
        self, _name, shape, allowlist, build_queued, expected_state, access_level=None, realtime_enabled_at=_ON
    ):
        # The send reads realtime membership from a Postgres database Django can't reach, so the
        # preview estimates from the cohort's periodic count and reports no email dedupe.
        self._create_audience(["a@x.com", "a@x.com", "b@x.com"])
        behavioral_leaf = {
            "key": "$pageview",
            "event_type": "events",
            "time_value": 30,
            "time_interval": "day",
            "value": "performed_event",
            "type": "behavioral",
        }
        leaves: list[dict] = [behavioral_leaf]
        if shape == "person_on_behavioral":
            inner = Cohort.objects.create(
                team=self.team,
                name="inner",
                cohort_type=CohortType.REALTIME,
                realtime_enabled_at=_ON,
                filters={"properties": {"type": "AND", "values": [behavioral_leaf]}},
            )
            leaves = [
                {"key": "email", "type": "person", "value": "x.com", "operator": "icontains"},
                {"key": "id", "type": "cohort", "value": inner.pk},
            ]
        cohort = Cohort.objects.create(
            team=self.team,
            name="c",
            cohort_type=CohortType.REALTIME,
            realtime_enabled_at=realtime_enabled_at,
            count=2,
            filters={"properties": {"type": "AND", "values": leaves}},
        )
        if access_level is not None:
            RealtimeCohortTeamAccess.objects.create(
                team=self.team, level=access_level, purpose=RealtimeCohortAccessPurpose.LOAD_TEST
            )
        if build_queued:
            get_redis_client().set(
                cohort_backfill_pending_key(cohort.pk, CohortBackfillKind.BEHAVIORAL),
                CohortBackfillTrigger.COHORT_CREATED,
                ex=300,
            )

        with override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=allowlist):
            size = get_audience_size(
                team_id=self.team.pk,
                filters={"properties": [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "in"}]},
                group_type_index=None,
                dedupe_key="email",
                sends_email=True,
            )

        assert (size.affected, size.total, size.dedupe_key) == (2, 3, None)
        assert size.realtime_cohort is not None
        assert (size.realtime_cohort.id, size.realtime_cohort.state) == (cohort.pk, expected_state)

    @parameterized.expand(
        [
            ("realtime", True, False, True),
            ("not_realtime", False, False, False),
            # The pickers can only show and clear top-level conditions, so a nested cohort isn't flagged.
            ("realtime_nested_in_a_group", True, True, False),
        ]
    )
    def test_audience_size_flags_a_realtime_cohort_mixed_with_other_conditions(
        self, _name, realtime, nested, expect_flagged
    ):
        self._create_audience(["a@x.com"])
        cohort = Cohort.objects.create(
            team=self.team,
            name="c",
            cohort_type=CohortType.REALTIME if realtime else None,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 30,
                            "time_interval": "day",
                            "value": "performed_event",
                            "type": "behavioral",
                        }
                    ],
                }
            },
        )

        conditions = [
            {"key": "id", "type": "cohort", "value": cohort.pk, "operator": "in"},
            {"key": "email", "type": "person", "value": "x.com", "operator": "icontains"},
        ]
        size = get_audience_size(
            team_id=self.team.pk,
            filters={"properties": [{"type": "AND", "values": conditions}] if nested else conditions},
            group_type_index=None,
            dedupe_key=None,
            sends_email=True,
        )

        assert size.realtime_cohort is None
        mixed = size.realtime_cohort_with_other_conditions
        assert (mixed.id if mixed else None) == (cohort.pk if expect_flagged else None)

    @parameterized.expand(
        [
            ("same_audience_cached", False, False, (2, 2)),
            ("refreshed_count_reused", True, False, (2, 2)),
            ("refresh_counts_again", False, True, (3, 3)),
        ]
    )
    def test_audience_size_reuses_a_recent_count_of_the_same_audience(self, _name, first_refresh, refresh, expected):
        self._create_audience(["a@x.com", "b@x.com"])
        get_audience_size(
            team_id=self.team.pk,
            filters=FILTERS,
            group_type_index=None,
            dedupe_key=None,
            sends_email=True,
            refresh=first_refresh,
        )
        _create_person(team=self.team, distinct_ids=["user-3"], uuid=_uuid(3), properties={"subscribed": "true"})
        flush_persons_and_events()

        size = get_audience_size(
            team_id=self.team.pk,
            filters=FILTERS,
            group_type_index=None,
            dedupe_key=None,
            sends_email=True,
            refresh=refresh,
        )

        assert (size.affected, size.total) == expected

    @parameterized.expand(
        [
            ("persons", None, 0, (2, 3)),
            ("unique_emails", "email", 0, (2, 3)),
            ("small_total_counted_again", None, 10_000, (2, 4)),
        ]
    )
    def test_audience_size_counts_a_new_audience_but_reuses_the_recent_person_total(
        self, _name, dedupe_key, min_total_to_cache, expected
    ):
        patcher = patch(
            "products.workflows.backend.services.blast_radius.MIN_PERSON_TOTAL_TO_CACHE", min_total_to_cache
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self._create_audience(["a@x.com", "b@x.com"])
        _create_person(
            team=self.team,
            distinct_ids=["user-3"],
            uuid=_uuid(3),
            properties={"subscribed": "false", "email": "c@x.com"},
        )
        flush_persons_and_events()
        get_audience_size(
            team_id=self.team.pk,
            filters=FILTERS,
            group_type_index=None,
            dedupe_key=None,
            sends_email=True,
            refresh=False,
        )
        _create_person(
            team=self.team,
            distinct_ids=["user-4"],
            uuid=_uuid(4),
            properties={"subscribed": "false", "email": "d@x.com"},
        )
        flush_persons_and_events()

        size = get_audience_size(
            team_id=self.team.pk,
            filters={"properties": [{"key": "subscribed", "type": "person", "value": ["false"], "operator": "exact"}]},
            group_type_index=None,
            dedupe_key=dedupe_key,
            sends_email=True,
            refresh=False,
        )

        assert (size.affected, size.total) == expected

    @parameterized.expand(
        [
            ("count_in_flight_finishes", "finishes", 999),
            ("count_in_flight_fails", "fails", 2),
            ("count_in_flight_never_ends", "hangs", 2),
            ("another_waiter_took_over", "taken_over", None),
        ]
    )
    def test_audience_size_waits_for_the_same_count_in_flight(self, _name, other_request, expected_total):
        self._create_audience(["a@x.com", "b@x.com"])
        total_key = f"workflows:audience_person_total:{self.team.pk}"
        cache.set(f"{total_key}:counting", "other-request", 600)
        if other_request == "taken_over":
            cache.set(f"{total_key}:takeover", "other-waiter", 600)
        clock = iter(range(0, 10_000, 10))

        def other_request_progresses(_seconds: float) -> None:
            if other_request == "finishes":
                cache.set(total_key, 999, 60)
            if other_request not in ("hangs", "taken_over"):
                cache.delete(f"{total_key}:counting")

        with (
            patch("products.workflows.backend.services.blast_radius.sleep", side_effect=other_request_progresses),
            patch("products.workflows.backend.services.blast_radius.monotonic", side_effect=lambda: next(clock)),
        ):
            if expected_total is None:
                with pytest.raises(AudienceCountInProgress):
                    get_audience_size(
                        team_id=self.team.pk,
                        filters=FILTERS,
                        group_type_index=None,
                        dedupe_key=None,
                        sends_email=True,
                        refresh=False,
                    )
                return
            size = get_audience_size(
                team_id=self.team.pk,
                filters=FILTERS,
                group_type_index=None,
                dedupe_key=None,
                sends_email=True,
                refresh=False,
            )

        assert (size.affected, size.total) == (2, expected_total)

    def test_audience_size_counts_again_after_the_test_account_filters_change(self):
        self._create_audience(["a@example.com", "b@internal.example.com"])

        def affected() -> int:
            return get_audience_size(
                team_id=self.team.pk,
                filters={**FILTERS, "filter_test_accounts": True},
                group_type_index=None,
                dedupe_key=None,
                sends_email=True,
                refresh=False,
            ).affected

        before = affected()
        self.team.test_account_filters = [
            {"key": "email", "type": "person", "value": "@internal.example.com", "operator": "not_icontains"}
        ]
        self.team.save()

        assert (before, affected()) == (2, 1)
