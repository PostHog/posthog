from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client import sync_execute

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.feature_flags.backend.user_blast_radius import get_user_blast_radius_persons
from products.workflows.backend.services.batch_audience import get_batch_audience_count, get_batch_audience_person_ids

FILTERS = {"properties": [{"key": "subscribed", "type": "person", "value": ["true"], "operator": "exact"}]}


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
            ("email_dedupe", "email", [1, 3, 4, 5]),
            ("no_dedupe", None, [1, 2, 3, 4, 5]),
        ]
    )
    def test_audience_dedupe_by_email(self, _name, dedupe_key, expected_indices):
        self._create_audience(["Dup@X.com", " dup@x.com ", "b@x.com", None, ""])

        result = get_batch_audience_person_ids(self.team, FILTERS, dedupe_key=dedupe_key)

        assert sorted(result) == [_uuid(i) for i in expected_indices]

    def test_count_matches_deduped_audience_size(self):
        self._create_audience(["Dup@X.com", " dup@x.com ", "b@x.com", None, ""])

        count = get_batch_audience_count(self.team, FILTERS, dedupe_key="email")

        assert count == len(get_batch_audience_person_ids(self.team, FILTERS, dedupe_key="email")) == 4

    def test_count_rejects_unsupported_dedupe_key(self):
        # Defence-in-depth: the endpoint's serializer allowlist is the primary gate, but this
        # raise forces a future maintainer adding a new supported key to teach the count
        # function about it too, rather than silently returning email-deduped counts.
        with pytest.raises(ValueError, match="Unsupported dedupe_key"):
            get_batch_audience_count(self.team, FILTERS, dedupe_key="sms")

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
        with patch("products.workflows.backend.services.batch_audience.PERSON_BATCH_SIZE", 2):
            for _ in range(10):
                page = get_batch_audience_person_ids(self.team, FILTERS, cursor=cursor, dedupe_key=dedupe_key)
                collected.extend(page)
                if len(page) < 2:
                    break
                cursor = page[-1]

        assert collected == [_uuid(i) for i in expected_indices]

    def _create_realtime_cohort(self, backfilled: bool = True) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            name="power-users",
            cohort_type=CohortType.REALTIME,
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
            last_backfill_events_at=datetime(2024, 1, 1, tzinfo=UTC) if backfilled else None,
        )

    def _add_membership(
        self, cohort_id: int, person_uuid: str, status: str, at: datetime, team_id: int | None = None
    ) -> None:
        sync_execute(
            "INSERT INTO cohort_membership (team_id, cohort_id, person_id, status, last_updated) VALUES",
            [(team_id if team_id is not None else self.team.pk, cohort_id, person_uuid, status, at)],
        )

    def _realtime_cohort_filters(self, cohort_id: int, extra_properties: list | None = None) -> dict:
        return {
            "properties": [
                {"key": "id", "type": "cohort", "value": cohort_id, "operator": "in"},
                *(extra_properties or []),
            ]
        }

    def test_realtime_cohort_audience_returns_current_members_only(self):
        self._create_audience(["a@x.com", "b@x.com", "c@x.com"])
        cohort = self._create_realtime_cohort()
        t0, t1 = datetime(2024, 6, 1, tzinfo=UTC), datetime(2024, 6, 2, tzinfo=UTC)
        self._add_membership(cohort.pk, _uuid(1), "entered", t0)
        # Entered then left: only the latest status counts.
        self._add_membership(cohort.pk, _uuid(2), "entered", t0)
        self._add_membership(cohort.pk, _uuid(2), "left", t1)
        # Same cohort id, different team: must never leak across the tenant boundary.
        self._add_membership(cohort.pk, _uuid(3), "entered", t0, team_id=self.team.pk + 1)

        filters = self._realtime_cohort_filters(cohort.pk)

        assert get_batch_audience_person_ids(self.team, filters) == [_uuid(1)]
        assert get_batch_audience_count(self.team, filters, dedupe_key="email") == 1

    def test_realtime_cohort_intersects_with_person_property_filters(self):
        self._create_audience(["a@x.com", "b@x.com"])
        _create_person(team=self.team, distinct_ids=["user-3"], uuid=_uuid(3), properties={"subscribed": "false"})
        flush_persons_and_events()
        cohort = self._create_realtime_cohort()
        for index in (1, 2, 3):
            self._add_membership(cohort.pk, _uuid(index), "entered", datetime(2024, 6, 1, tzinfo=UTC))

        filters = self._realtime_cohort_filters(
            cohort.pk,
            extra_properties=[{"key": "email", "type": "person", "value": "a@x.com", "operator": "exact"}],
        )

        # Person 2 is a member but fails the property filter; person 3 fails both.
        assert get_batch_audience_person_ids(self.team, filters) == [_uuid(1)]

    def test_realtime_cohort_that_lost_eligibility_fails_loudly(self):
        # Trigger filters are snapshotted onto batch jobs, so the cohort can lose its backfill
        # stamps between save and run; enumerating it anyway would send to the wrong people.
        cohort = self._create_realtime_cohort(backfilled=False)

        with pytest.raises(ValidationError, match="isn't ready for realtime evaluation"):
            get_batch_audience_person_ids(self.team, self._realtime_cohort_filters(cohort.pk))
