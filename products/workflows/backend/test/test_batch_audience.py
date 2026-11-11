from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.redis import get_client as get_redis_client

from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillTrigger
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.dependencies import cohort_backfill_pending_key
from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.feature_flags.backend.user_blast_radius import PERSON_BATCH_SIZE, get_user_blast_radius_persons
from products.workflows.backend.services.batch_audience import audience_page_size, get_batch_audience_person_ids
from products.workflows.backend.services.blast_radius import get_audience_size

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
        ]
    )
    def test_realtime_cohort_audience_size_estimates_from_the_cohort_count(
        self, _name, shape, allowlist, build_queued, expected_state, access_level=None
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
