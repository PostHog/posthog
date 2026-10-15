from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client import sync_execute

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.feature_flags.backend.user_blast_radius import PERSON_BATCH_SIZE, get_user_blast_radius_persons
from products.workflows.backend.services.audience_v2 import get_dedupe_audience_count_v2, get_person_audience_count_v2
from products.workflows.backend.services.batch_audience import audience_page_size, get_batch_audience_person_ids
from products.workflows.backend.services.batch_audience_cohorts import lower_realtime_cohorts
from products.workflows.backend.services.realtime_membership_lag import RealtimeMembershipLagging

FILTERS = {"properties": [{"key": "subscribed", "type": "person", "value": ["true"], "operator": "exact"}]}


def _uuid(index: int) -> str:
    # Only the last digit differs, so string ordering and ClickHouse UUID ordering agree.
    return f"01970000-0000-0000-0000-00000000000{index}"


class TestBatchAudience(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        # Realtime membership counts as current unless a test says otherwise.
        lag_patcher = patch(
            "products.workflows.backend.services.realtime_membership_lag.measure_realtime_membership_lag_seconds",
            return_value=0.0,
        )
        lag_patcher.start()
        self.addCleanup(lag_patcher.stop)

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
            ("email_dedupe", "email", [1, 3, 4, 5]),
            ("no_dedupe", None, [1, 2, 3, 4, 5]),
        ]
    )
    def test_audience_dedupe_by_email(self, _name, dedupe_key, expected_indices):
        self._create_audience(["Dup@X.com", " dup@x.com ", "b@x.com", None, ""])

        result = get_batch_audience_person_ids(self.team, FILTERS, dedupe_key=dedupe_key)

        assert sorted(result) == [_uuid(i) for i in expected_indices]

    def test_audience_without_dedupe_matches_legacy_query(self):
        self._create_audience(["a@x.com", "a@x.com", "b@x.com", None])

        assert sorted(get_batch_audience_person_ids(self.team, FILTERS)) == sorted(
            get_user_blast_radius_persons(self.team, FILTERS)
        )

    @parameterized.expand(
        [
            ("email_dedupe", "email", [1, 2, 3, 5]),
            ("no_dedupe", None, [1, 2, 3, 4, 5]),
        ]
    )
    def test_pagination_emits_each_email_exactly_once(self, _name, dedupe_key, expected_indices):
        # Person 4 duplicates person 1's email but sorts onto a later page — if the cursor
        # were applied inside the aggregation, min(id) would be recomputed per page and
        # a@x.com would be emitted twice.
        self._create_audience(["a@x.com", "b@x.com", "c@x.com", "a@x.com", None])

        collected: list[str] = []
        cursor = None
        with override_settings(WORKFLOWS_PERSON_BATCH_SIZE=2):
            for _ in range(10):
                page = get_batch_audience_person_ids(self.team, FILTERS, cursor=cursor, dedupe_key=dedupe_key)
                collected.extend(page)
                if len(page) < 2:
                    break
                cursor = page[-1]

        assert collected == [_uuid(i) for i in expected_indices]

    @override_settings(WORKFLOWS_PERSON_BATCH_SIZE=7)
    def test_has_more_page_size_follows_the_audience_kind(self):
        # A group audience pages through the flags-owned query with its own limit; comparing its
        # page length against the person setting would stop after the first page.
        assert audience_page_size(None) == 7
        assert audience_page_size(0) == PERSON_BATCH_SIZE

    def _create_realtime_cohort(self, *, behavioral: bool = True, backfilled: bool = True) -> Cohort:
        leaf = (
            {
                "key": "$pageview",
                "event_type": "events",
                "time_value": 30,
                "time_interval": "day",
                "value": "performed_event",
                "type": "behavioral",
            }
            if behavioral
            else {"key": "email", "type": "person", "value": "a@x.com", "operator": "exact"}
        )
        backfilled_at = datetime(2026, 1, 1, tzinfo=UTC) if backfilled else None
        return Cohort.objects.create(
            team=self.team,
            name="power-users",
            cohort_type=CohortType.REALTIME,
            filters={"properties": {"type": "AND", "values": [leaf]}},
            last_backfill_events_at=backfilled_at,
            last_backfill_person_properties_at=backfilled_at,
        )

    def _add_membership(self, cohort_id: int, person_id: str, status: str, hour: int, team_id: int | None = None):
        sync_execute(
            "INSERT INTO realtime_cohort_membership (team_id, cohort_id, person_id, status, last_updated, origin) VALUES",
            [
                (
                    team_id if team_id is not None else self.team.pk,
                    cohort_id,
                    person_id,
                    status,
                    datetime(2026, 10, 1, hour, tzinfo=UTC),
                    "",
                )
            ],
        )

    @parameterized.expand([("in", "in", [1]), ("not_in", "not_in", [2, 3])])
    def test_realtime_cohort_audience_reads_current_membership(self, _name, operator, expected_indices):
        self._create_audience(["a@x.com", "b@x.com", "c@x.com"])
        cohort = self._create_realtime_cohort()
        self._add_membership(cohort.pk, _uuid(1), "entered", hour=1)
        # Only the latest status counts.
        self._add_membership(cohort.pk, _uuid(2), "entered", hour=1)
        self._add_membership(cohort.pk, _uuid(2), "left", hour=2)
        # A row of another team must never reach this team's audience.
        self._add_membership(cohort.pk, _uuid(3), "entered", hour=1, team_id=self.team.pk + 1)
        filters = {"properties": [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": operator}]}

        assert sorted(get_batch_audience_person_ids(self.team, filters)) == [_uuid(i) for i in expected_indices]
        assert get_person_audience_count_v2(self.team, filters).affected == len(expected_indices)
        assert get_dedupe_audience_count_v2(self.team, filters, "email").affected == len(expected_indices)

    def test_realtime_cohort_audience_intersects_with_person_properties(self):
        self._create_audience(["a@x.com", "b@x.com"])
        cohort = self._create_realtime_cohort()
        self._add_membership(cohort.pk, _uuid(1), "entered", hour=1)
        self._add_membership(cohort.pk, _uuid(2), "entered", hour=1)
        filters = {
            "properties": [
                {"key": "id", "type": "cohort", "value": cohort.pk, "operator": "in"},
                {"key": "email", "type": "person", "value": "a@x.com", "operator": "exact"},
            ]
        }

        assert get_batch_audience_person_ids(self.team, filters) == [_uuid(1)]

    def test_realtime_cohort_that_lost_readiness_fails_instead_of_resolving(self):
        # Batch jobs snapshot the trigger filters, so a cohort can lose readiness between save and
        # run. Resolving it anyway would send to the wrong people.
        cohort = self._create_realtime_cohort(backfilled=False)
        filters = {"properties": [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "in"}]}

        with pytest.raises(ValidationError, match="isn't ready for realtime evaluation"):
            get_batch_audience_person_ids(self.team, filters)

    def test_person_property_realtime_cohort_keeps_inline_evaluation(self):
        # Audiences that used such a cohort before realtime membership existed must not start
        # reading a table that may not hold their members yet.
        cohort = self._create_realtime_cohort(behavioral=False)
        filters = {"properties": [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "in"}]}

        assert lower_realtime_cohorts(self.team, filters) == filters

    @parameterized.expand(
        [
            ("first_page_lagging", None, True, 600.0, True),
            ("first_page_current", None, True, 10.0, False),
            ("first_page_unmeasurable", None, True, RuntimeError("broker unreachable"), True),
            # Later pages trust the check the first page passed.
            ("later_page", _uuid(1), True, 600.0, False),
            ("no_realtime_cohort", None, False, 600.0, False),
        ]
    )
    @override_settings(WORKFLOWS_REALTIME_COHORT_MAX_LAG_SECONDS=300)
    def test_realtime_cohort_audience_waits_for_current_membership(
        self, _name, cursor, reads_realtime, measured_lag, expect_lagging
    ):
        self._create_audience(["a@x.com", "b@x.com"])
        cohort = self._create_realtime_cohort()
        self._add_membership(cohort.pk, _uuid(2), "entered", hour=1)
        filters = (
            {"properties": [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "in"}]}
            if reads_realtime
            else FILTERS
        )

        with patch(
            "products.workflows.backend.services.realtime_membership_lag.measure_realtime_membership_lag_seconds",
            side_effect=[measured_lag],
        ):
            if expect_lagging:
                with pytest.raises(RealtimeMembershipLagging):
                    get_batch_audience_person_ids(self.team, filters, cursor=cursor)
            else:
                get_batch_audience_person_ids(self.team, filters, cursor=cursor)
