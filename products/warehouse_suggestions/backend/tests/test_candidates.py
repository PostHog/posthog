from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, log_activity

from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_modeling.backend.facade.models import DAG, DataModelingJob, DataWarehouseSavedQuery, Node, NodeType
from products.warehouse_suggestions.backend.facade.contracts import (
    CertifyPayload,
    MaterializePayload,
    UnmaterializePayload,
)
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionAssetOutcome,
    WarehouseSuggestionKind,
    WarehouseSuggestionRefreshIntervalBasis,
    WarehouseSuggestionRefreshMode,
)
from products.warehouse_suggestions.backend.logic.candidates.base import (
    DEPENDENTS_REJECTION,
    FEEDS_CONSUMERS_REJECTION,
    READER_ACCESS_REJECTION,
    CandidateContext,
)
from products.warehouse_suggestions.backend.logic.candidates.certify import CertifyCandidate
from products.warehouse_suggestions.backend.logic.candidates.deprecate import DeprecateCandidate
from products.warehouse_suggestions.backend.logic.candidates.materialize import (
    MaterializeCandidate,
    allowed_intervals,
    estimate_savings,
    interval_basis,
    refresh_cost,
)
from products.warehouse_suggestions.backend.logic.candidates.unmaterialize import UnmaterializeCandidate
from products.warehouse_suggestions.backend.logic.reads import RefreshRun, SubjectRefreshes
from products.warehouse_suggestions.backend.logic.rules import RULES, Surface
from products.warehouse_suggestions.backend.tests.factories import (
    busy_reads,
    context,
    days_ago,
    table_subject,
    team_reads,
    view,
    view_subject,
)

VIEW_ID = uuid4()
AT_CERTIFY_FLOORS = {"human_users": 5, "human_days": 20}
HOUR = timedelta(hours=1)
DAY = timedelta(hours=24)
DAILY_COUNTS = "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day"
DAILY_COUNT_COLUMNS = {
    "day": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime64(6, 'UTC')"},
    "c": {"hogql": "IntegerDatabaseField", "clickhouse": "UInt64"},
}


class TestCertifyCandidate(SimpleTestCase):
    @parameterized.expand(
        [
            ("at_every_floor", {}, 30, False, True),
            ("one_person_short", {"human_users": 4}, 30, False, False),
            ("one_day_short", {"human_days": 19}, 30, False, False),
            ("one_surface", {"requests_by_surface": {Surface.SQL_EDITOR: 200}}, 30, False, False),
            (
                "unknown_surface_does_not_count",
                {"requests_by_surface": {Surface.SQL_EDITOR: 100, Surface.UNKNOWN: 100}},
                30,
                False,
                False,
            ),
            ("day_floor_scales_while_warming_up", {"human_days": 10}, 15, False, True),
            ("already_certified", {}, 30, True, False),
        ]
    )
    def test_floors(
        self, _name: str, overrides: dict, days_with_data: int, certified: bool, expect_draft: bool
    ) -> None:
        subject = view_subject(VIEW_ID)
        reads = team_reads({subject: busy_reads(**{**AT_CERTIFY_FLOORS, **overrides})}, days_with_data=days_with_data)

        result = CertifyCandidate().evaluate(
            context(
                reads,
                views=[view(VIEW_ID)],
                certifications={subject: CertificationStatus.PROPOSED} if certified else {},
            )
        )

        assert [draft.subject_id for draft in result.drafts] == ([VIEW_ID] if expect_draft else [])

    @parameterized.expand(
        [
            ("two_person_team_read_by_both", 2, 2, True),
            ("solo_team", 1, 1, False),
            ("small_team_read_by_half", 6, 3, True),
            ("small_team_read_by_fewer_than_half", 6, 2, False),
            ("large_team_caps_at_five", 100, 5, True),
        ]
    )
    def test_people_floor_follows_team_size(
        self, _name: str, team_readers: int, human_users: int, expect_draft: bool
    ) -> None:
        reads = team_reads(
            {view_subject(VIEW_ID): busy_reads(**{**AT_CERTIFY_FLOORS, "human_users": human_users})},
            readers=team_readers,
        )

        result = CertifyCandidate().evaluate(context(reads, views=[view(VIEW_ID)]))

        assert [draft.subject_id for draft in result.drafts] == ([VIEW_ID] if expect_draft else [])

    @parameterized.expand(
        [
            ("still_certified", CertificationStatus.CERTIFIED, WarehouseSuggestionAssetOutcome.LIVE),
            ("changed_to_deprecated", CertificationStatus.DEPRECATED, WarehouseSuggestionAssetOutcome.UNUSED),
            ("removed", None, WarehouseSuggestionAssetOutcome.DELETED),
        ]
    )
    def test_records_what_became_of_an_accepted_certification(
        self, _name: str, current: CertificationStatus | None, expected: WarehouseSuggestionAssetOutcome
    ) -> None:
        subject = view_subject(VIEW_ID)
        ctx = context(team_reads({}), views=[view(VIEW_ID)], certifications={subject: current} if current else {})

        assert CertifyCandidate().asset_outcome(ctx, subject, accepted_at=None) == expected

    def test_only_the_top_share_by_requests_times_people_is_proposed(self) -> None:
        views = [view(uuid4(), name=f"view_{position}") for position in range(10)]
        reads = team_reads(
            {view_subject(v.id): busy_reads(human_requests=100 + position) for position, v in enumerate(views)}
        )

        result = CertifyCandidate().evaluate(context(reads, views=views))

        assert [draft.subject_id for draft in result.drafts] == [views[-1].id]

    def test_proposes_warehouse_tables_but_not_backing_tables_of_materialized_views(self) -> None:
        table_id, backing_table_id = uuid4(), uuid4()
        reads = team_reads({table_subject(table_id): busy_reads(), table_subject(backing_table_id): busy_reads()})

        result = CertifyCandidate().evaluate(context(reads, table_names={table_id: "stripe_charges"}))

        assert [(draft.subject_id, draft.payload) for draft in result.drafts] == [
            (table_id, CertifyPayload(subject_name="stripe_charges"))
        ]


class TestMaterializeRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("read_every_hour_on_most_days", 25, 25 * 24, [HOUR, timedelta(hours=6), DAY]),
            ("read_a_few_times_a_day", 25, 25 * 3, [DAY]),
            ("read_on_few_days", 10, 10 * 24, [DAY]),
        ]
    )
    def test_read_cadence_sets_the_shortest_interval(
        self, _name: str, human_days: int, human_requests: int, expected: list
    ) -> None:
        reads = busy_reads(human_days=human_days, human_requests=human_requests)

        intervals = allowed_intervals(
            context(team_reads({})), [HOUR, timedelta(hours=6), DAY, timedelta(days=7)], reads
        )

        assert intervals == expected

    @parameterized.expand(
        [
            ("at_floor", 90, 10_000.0, None, True),
            ("one_read_short", 89, 10_000.0, None, False),
            ("slow_reads_raise_the_refresh_price", 90, 20_000.0, None, False),
            (
                "recorded_refreshes_set_the_price",
                90,
                20_000.0,
                SubjectRefreshes(runs=3, duration_ms=30_000, read_bytes=3),
                True,
            ),
        ]
    )
    def test_time_saved_floor(
        self,
        _name: str,
        human_reads: int,
        alone_duration_ms_p90: float,
        refreshes: SubjectRefreshes | None,
        expect_clear: bool,
    ) -> None:
        reads = busy_reads(
            human_reads=human_reads,
            human_duration_ms=human_reads * 10_000,
            alone_duration_ms_median=10_000.0,
            alone_duration_ms_p90=alone_duration_ms_p90,
            human_read_bytes=human_reads,
            alone_read_bytes_median=1.0,
            alone_read_bytes_p90=1.0,
        )
        ctx = context(team_reads({}, refreshes={VIEW_ID: refreshes} if refreshes else None))

        estimate = estimate_savings(ctx, reads, DAY, refresh_cost(ctx, VIEW_ID, reads))

        assert estimate.clears_a_floor is expect_clear

    @parameterized.expand(
        [
            (
                "sources_allow_nothing_finer",
                HOUR,
                [HOUR, DAY],
                True,
                WarehouseSuggestionRefreshIntervalBasis.SOURCE_SYNC,
            ),
            (
                "nothing_refreshes_faster",
                HOUR,
                [HOUR, DAY],
                False,
                WarehouseSuggestionRefreshIntervalBasis.FASTEST_SCHEDULE,
            ),
            ("reads_allow_nothing_finer", DAY, [DAY], False, WarehouseSuggestionRefreshIntervalBasis.READ_RATE),
            (
                "finer_ones_save_too_little",
                DAY,
                [timedelta(hours=6), DAY],
                False,
                WarehouseSuggestionRefreshIntervalBasis.SAVINGS,
            ),
        ]
    )
    def test_interval_basis_names_what_kept_the_interval_from_being_shorter(
        self,
        _name: str,
        interval: timedelta,
        read_allowed: list[timedelta],
        limited_by_sources: bool,
        expected: WarehouseSuggestionRefreshIntervalBasis,
    ) -> None:
        basis = interval_basis(
            interval, [HOUR, timedelta(hours=6), DAY], read_allowed, limited_by_sources=limited_by_sources
        )

        assert basis == expected


class TestMaterializeRefreshMode(BaseTest):
    @parameterized.expand(
        [
            ("grouped_by_day", DAILY_COUNTS, WarehouseSuggestionRefreshMode.INCREMENTAL, "day", ("day",)),
            (
                "limited_query",
                "SELECT timestamp, event FROM events ORDER BY timestamp DESC LIMIT 10",
                WarehouseSuggestionRefreshMode.FULL,
                None,
                (),
            ),
            (
                "grouped_over_a_nondeterministic_view",
                DAILY_COUNTS.replace("FROM events", "FROM sampled_events"),
                WarehouseSuggestionRefreshMode.FULL,
                None,
                (),
            ),
        ]
    )
    def test_a_suggestion_proposes_incremental_only_when_the_keys_are_certain(
        self,
        _name: str,
        hogql: str,
        refresh_mode: WarehouseSuggestionRefreshMode,
        incremental_key: str | None,
        unique_key: tuple[str, ...],
    ) -> None:
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="sampled_events",
            query={"kind": "HogQLQuery", "query": "SELECT timestamp FROM events WHERE rand() % 10 = 0"},
            columns={"timestamp": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime64(6, 'UTC')"}},
        )
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="daily_counts",
            query={"kind": "HogQLQuery", "query": hogql},
            columns=DAILY_COUNT_COLUMNS,
        )
        dag = DAG.objects.create(team=self.team, name="Default")
        Node.objects.create(team=self.team, dag=dag, name="daily_counts", saved_query=saved_query, type=NodeType.VIEW)
        candidate_context = context(
            team_reads({view_subject(saved_query.id): busy_reads(human_duration_ms=200 * 10_000)}),
            views=[view(saved_query.id, name="daily_counts", hogql=hogql)],
            team_id=self.team.pk,
        )

        [draft] = MaterializeCandidate().evaluate(candidate_context).drafts

        assert isinstance(draft.payload, MaterializePayload)
        expected_lookback = RULES.materialize.incremental_lookback_seconds if incremental_key else 0
        assert (
            draft.payload.refresh_mode,
            draft.payload.incremental_key,
            draft.payload.unique_key,
            draft.payload.lookback_seconds,
        ) == (refresh_mode, incremental_key, unique_key, expected_lookback)


class TestDeprecateCandidate(SimpleTestCase):
    def test_waits_for_a_full_window_of_read_data(self) -> None:
        materialized = view(VIEW_ID, materializes=True)

        result = DeprecateCandidate().evaluate(context(team_reads({}, days_with_data=29), views=[materialized]))

        assert (result.drafts, result.skipped_reason) == ((), "needs 30 days of read data, has 29")


class TestDeprecateBackgroundReads(BaseTest):
    @parameterized.expand([("background_reads_count", True, []), ("only_people_count", False, [VIEW_ID])])
    def test_a_view_read_only_by_background_traffic(
        self, _name: str, counts_background_reads: bool, expected_subjects: list
    ) -> None:
        rules = replace(RULES, deprecate=replace(RULES.deprecate, counts_background_reads=counts_background_reads))
        reads = team_reads(
            {view_subject(VIEW_ID): busy_reads(human_requests=0, human_users=0, human_days=0, background_requests=40)}
        )
        candidate_context = context(reads, views=[view(VIEW_ID, materializes=True)], team_id=self.team.pk, rules=rules)

        result = DeprecateCandidate().evaluate(candidate_context)

        assert [draft.subject_id for draft in result.drafts] == expected_subjects

    def test_a_view_feeding_a_consumer_is_not_proposed(self) -> None:
        candidate_context = context(team_reads({}), views=[view(VIEW_ID, materializes=True)], team_id=self.team.pk)

        with patch(
            "products.warehouse_suggestions.backend.logic.candidates.deprecate.saved_queries_feeding_consumers",
            return_value=frozenset({VIEW_ID}),
        ):
            result = DeprecateCandidate().evaluate(candidate_context)

        assert (result.drafts, [rejection.reason for rejection in result.rejections]) == (
            (),
            [FEEDS_CONSUMERS_REJECTION],
        )


HOURLY_RUNS = 720
FIVE_SECONDS_MS = 5_000
TWENTY_SECONDS_MS = 20_000
RARE_READS = {"human_requests": 4, "human_reads": 4, "background_reads": 0}
UNMATERIALIZE_MODULE = "products.warehouse_suggestions.backend.logic.candidates.unmaterialize"


def hourly_runs(
    count: int = HOURLY_RUNS, *, duration_ms: int = FIVE_SECONDS_MS, prefix: str = "run"
) -> tuple[RefreshRun, ...]:
    return tuple(
        RefreshRun(workflow_id=f"{prefix}-{index}", duration_ms=duration_ms, read_bytes=10**6) for index in range(count)
    )


def unmaterialize_context(
    team_id: int,
    *,
    view_overrides: dict | None = None,
    read_overrides: dict | None = None,
    runs: tuple[RefreshRun, ...] | None = None,
    recent_accepts: dict | None = None,
) -> CandidateContext:
    subject = view_subject(VIEW_ID)
    return context(
        team_reads(
            {subject: busy_reads(**{**RARE_READS, **(read_overrides or {})})},
            refresh_runs={VIEW_ID: hourly_runs() if runs is None else runs},
        ),
        views=[view(VIEW_ID, materializes=True, **(view_overrides or {}))],
        team_id=team_id,
        recent_accepts=recent_accepts,
    )


class TestUnmaterializeCandidate(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            id=VIEW_ID, team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )

    def _record_jobs(self, runs: tuple[RefreshRun, ...], **job_fields: Any) -> None:
        DataModelingJob.objects.bulk_create(
            DataModelingJob(
                team=self.team,
                saved_query=self.saved_query,
                workflow_id=run.workflow_id,
                status=job_fields.get("status", DataModelingJob.Status.COMPLETED),
                run_mode=job_fields.get("run_mode", DataModelingJob.RunMode.FULL_REFRESH),
                engine=job_fields.get("engine", DataModelingJob.Engine.CLICKHOUSE),
            )
            for run in runs
        )
        if "created_at" in job_fields:
            DataModelingJob.objects.filter(workflow_id__in=[run.workflow_id for run in runs]).update(
                created_at=job_fields["created_at"]
            )

    def _log_query_change(self, at: Any) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.pk,
                user=self.user,
                was_impersonated=False,
                item_id=VIEW_ID,
                scope="DataWarehouseSavedQuery",
                activity="updated",
                detail=Detail(
                    name="orders",
                    changes=[
                        Change(type="DataWarehouseSavedQuery", action="changed", field="query", before="a", after="b")
                    ],
                ),
            )
        ActivityLog.objects.filter(item_id=str(VIEW_ID)).update(created_at=at)

    def test_proposes_a_rarely_read_view_with_refresh_cost_against_live_cost(self) -> None:
        self._record_jobs(hourly_runs())

        result = UnmaterializeCandidate().evaluate(unmaterialize_context(self.team.pk))

        [draft] = result.drafts
        assert isinstance(draft.payload, UnmaterializePayload)
        assert replace(draft.payload, query_fingerprint="") == UnmaterializePayload(
            subject_name="orders",
            refresh_seconds_per_month=3600.0,
            refresh_bytes_per_month=720.0 * 10**6,
            live_seconds_per_month=20.0,
            live_bytes_per_month=4.0 * 10**6,
            read_seconds=5.0,
            query_fingerprint="",
        )

    @parameterized.expand(
        [
            ("few_runs", {}, {}, hourly_runs(2), None, "has 2 completed full refreshes"),
            ("incremental", {"refreshes_incrementally": True}, {}, None, None, "refreshes incrementally"),
            (
                "calls_a_decision_function",
                {"calls_decision_functions": True},
                {},
                None,
                None,
                "calls jev() or decide()",
            ),
            (
                "materialized_on_a_recent_suggestion",
                {},
                {},
                None,
                {WarehouseSuggestionKind.MATERIALIZE: frozenset({VIEW_ID})},
                "was materialized on a suggestion",
            ),
            ("read_too_often", {}, {"human_reads": 600}, None, None, "would not save enough"),
            ("background_reads_count", {}, {"background_reads": 600}, None, None, "would not save enough"),
            (
                "slow_tail",
                {},
                {},
                hourly_runs(duration_ms=TWENTY_SECONDS_MS),
                None,
                "a read could take 20 seconds",
            ),
        ]
    )
    def test_rejects_a_view_that_would_cost_more_or_read_slowly_when_computed_on_read(
        self,
        _name: str,
        view_overrides: dict,
        read_overrides: dict,
        runs: tuple[RefreshRun, ...] | None,
        recent_accepts: dict | None,
        expected_reason: str,
    ) -> None:
        self._record_jobs(runs or hourly_runs())
        candidate_context = unmaterialize_context(
            self.team.pk,
            view_overrides=view_overrides,
            read_overrides=read_overrides,
            runs=runs,
            recent_accepts=recent_accepts,
        )

        result = UnmaterializeCandidate().evaluate(candidate_context)

        [rejection] = result.rejections
        assert (result.drafts, expected_reason in rejection.reason) == ((), True), rejection.reason

    @parameterized.expand(
        [
            ("failed", {"status": DataModelingJob.Status.FAILED}, False),
            ("incremental", {"run_mode": DataModelingJob.RunMode.INCREMENTAL}, False),
            ("another_engine", {"engine": DataModelingJob.Engine.LEGACY_DUCKGRES}, False),
            ("before_the_query_changed", {"created_at": days_ago(10)}, True),
        ]
    )
    def test_prices_only_completed_full_refreshes_of_the_current_query(
        self, _name: str, fast_job_fields: dict, query_changed: bool
    ) -> None:
        slow = hourly_runs(10, duration_ms=TWENTY_SECONDS_MS, prefix="slow")
        fast = hourly_runs(HOURLY_RUNS - 10, prefix="fast")
        self._record_jobs(slow)
        self._record_jobs(fast, **fast_job_fields)
        if query_changed:
            self._log_query_change(days_ago(5))

        result = UnmaterializeCandidate().evaluate(unmaterialize_context(self.team.pk, runs=slow + fast))

        assert (result.drafts, [rejection.reason for rejection in result.rejections]) == (
            (),
            ["a read could take 20 seconds, over 10"],
        )

    @parameterized.expand(
        [
            ("has_dependents", "dependent_saved_query_ids", {VIEW_ID: frozenset({uuid4()})}, DEPENDENTS_REJECTION),
            (
                "feeds_a_consumer",
                "saved_queries_feeding_consumers",
                frozenset({VIEW_ID}),
                FEEDS_CONSUMERS_REJECTION,
            ),
            ("readers_could_lose_access", "inlining_could_deny_a_reader", True, READER_ACCESS_REJECTION),
        ]
    )
    def test_rejects_a_view_others_rely_on(self, _name: str, lookup: str, found: object, expected_reason: str) -> None:
        self._record_jobs(hourly_runs())
        with patch(f"{UNMATERIALIZE_MODULE}.{lookup}", return_value=found):
            result = UnmaterializeCandidate().evaluate(unmaterialize_context(self.team.pk))

        assert (result.drafts, [rejection.reason for rejection in result.rejections]) == ((), [expected_reason])

    def test_leaves_an_unread_view_to_deprecate(self) -> None:
        candidate_context = context(
            team_reads({}, refresh_runs={VIEW_ID: hourly_runs()}),
            views=[view(VIEW_ID, materializes=True)],
            team_id=self.team.pk,
        )

        result = UnmaterializeCandidate().evaluate(candidate_context)

        assert (result.drafts, result.rejections) == ((), ())


class TestMaterializeAfterUnmaterialize(SimpleTestCase):
    def test_a_view_unmaterialized_on_a_recent_suggestion_is_not_proposed_again(self) -> None:
        candidate_context = context(
            team_reads({view_subject(VIEW_ID): busy_reads()}),
            views=[view(VIEW_ID)],
            recent_accepts={WarehouseSuggestionKind.UNMATERIALIZE: frozenset({VIEW_ID})},
        )

        result = MaterializeCandidate().evaluate(candidate_context)

        assert (result.drafts, [rejection.reason for rejection in result.rejections]) == (
            (),
            ["was unmaterialized on a suggestion in the last 30 days"],
        )
