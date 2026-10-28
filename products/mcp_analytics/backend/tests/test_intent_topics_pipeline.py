import os

os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")

from datetime import timedelta  # noqa: E402

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events  # noqa: E402
from unittest.mock import patch  # noqa: E402

import numpy as np  # noqa: E402

from posthog.schema import DateRange, MCPIntentTopicsQuery  # noqa: E402

from posthog.hogql.parser import parse_select  # noqa: E402
from posthog.hogql.query import execute_hogql_query  # noqa: E402

from posthog.models.team.team import Team  # noqa: E402

from products.mcp_analytics.backend.hogql_queries.intent_topics import MCPIntentTopicsQueryRunner  # noqa: E402
from products.mcp_analytics.backend.intent_hash import intent_hash  # noqa: E402
from products.mcp_analytics.backend.intent_topics import persist, pipeline, rollups  # noqa: E402
from products.mcp_analytics.backend.intent_topics.corpus import HourlyCalls  # noqa: E402
from products.mcp_analytics.backend.intent_topics.labeling import TopicLabel  # noqa: E402
from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentTopic  # noqa: E402
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin  # noqa: E402
from products.mcp_analytics.backend.tests.intent_topics_helpers import insert_intent_embedding, recent_hour
from products.mcp_analytics.backend.tests.test_intent_assignments_table import _insert_assignment  # noqa: E402
from products.mcp_analytics.backend.tests.test_intent_topics_clustering import skip_without_umap  # noqa: E402

NOW = recent_hour(days_ago=0)


def _blob_vectors(axis: int, n: int, seed: int) -> list[list[float]]:
    rng = np.random.default_rng(seed)
    base = np.zeros(256)
    base[axis] = 1.0
    return (base + rng.normal(scale=0.02, size=(n, 256))).tolist()


class TestRunSync(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_emits_only_intents_without_a_vector_and_records_the_run(self, mock_emit) -> None:
        for text in ("new intent", "new intent", "already embedded"):
            _create_event(
                team=self.team,
                event="$mcp_tool_call",
                distinct_id="a",
                timestamp=NOW - timedelta(minutes=30),
                properties={"$mcp_tool_name": "query-trends", "$mcp_intent": text},
            )
        flush_persons_and_events()
        insert_intent_embedding(
            self.team.pk, intent_hash("already embedded"), "already embedded", at=NOW - timedelta(days=1)
        )

        outcome = pipeline.run_sync(self.team, window_start=NOW - timedelta(hours=1), window_end=NOW)

        assert (outcome.status, outcome.n_intents, outcome.n_embeddings_requested) == ("succeeded", 2, 1)
        assert mock_emit.call_args.kwargs["document_id"] == intent_hash("new intent")
        assert mock_emit.call_args.kwargs["metadata"]["calls"] == 2
        run = MCPIntentClusteringRun.objects.get(team=self.team, run_id=outcome.run_id)
        assert run.kind == "sync" and run.n_embeddings_requested == 1
        hourly = execute_hogql_query(
            query="SELECT intent_hash, tool, calls FROM posthog.mcp_intent_calls_hourly ORDER BY calls DESC",
            team=self.team,
        ).results
        assert hourly == [
            (intent_hash("new intent"), "query-trends", 2),
            (intent_hash("already embedded"), "query-trends", 1),
        ]

    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_replaying_a_window_after_late_events_replaces_its_counts(self, _mock_emit) -> None:
        def call(minutes_ago: int, session: str) -> None:
            _create_event(
                team=self.team,
                event="$mcp_tool_call",
                distinct_id="a",
                timestamp=NOW - timedelta(minutes=minutes_ago),
                properties={
                    "$mcp_tool_name": "query-trends",
                    "$mcp_intent": "plot signups",
                    "$mcp_session_id": session,
                },
            )

        start = NOW - timedelta(hours=1)
        call(50, "s1")
        flush_persons_and_events()
        pipeline.run_sync(self.team, window_start=start, window_end=NOW)
        call(40, "s2")
        call(30, "s3")
        flush_persons_and_events()
        pipeline.run_sync(self.team, window_start=start, window_end=NOW)

        hourly = execute_hogql_query(
            query=parse_select(
                "SELECT calls, length(conversation_hashes) FROM {hourly}",
                placeholders={"hourly": rollups.hourly_calls_source(since=start, until=NOW)},
            ),
            team=self.team,
        ).results
        _insert_assignment(self.team.pk, intent_hash("plot signups"), "topic-a")
        rollups.rebuild_topic_daily(team_id=self.team.pk, window_start=start, window_end=NOW, now=NOW)
        daily = execute_hogql_query(
            query="SELECT calls, length(conversation_hashes) FROM posthog.mcp_intent_topic_daily", team=self.team
        ).results

        assert (hourly, daily) == ([(3, 3)], [(3, 3)])

    def _call(self, text: str, at, team: Team | None = None) -> None:
        _create_event(
            team=team or self.team,
            event="$mcp_tool_call",
            distinct_id="a",
            timestamp=at,
            properties={"$mcp_tool_name": "query-trends", "$mcp_intent": text},
        )

    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_a_window_over_the_budget_is_drained_across_runs_without_losing_intents(self, mock_emit) -> None:
        start = NOW - timedelta(hours=3)
        for text, hour in (("a", 0), ("b", 0), ("a", 1), ("c", 1), ("d", 2)):
            self._call(text, start + timedelta(hours=hour, minutes=20))
        flush_persons_and_events()

        first = pipeline.run_sync(self.team, window_start=start, window_end=NOW, budget=2, page_size=1)

        assert (first.status, first.n_intents) == ("succeeded", 2)
        assert MCPIntentClusteringRun.objects.get(run_id=first.run_id).window_end == start + timedelta(hours=1)
        for call in mock_emit.call_args_list:
            insert_intent_embedding(self.team.pk, call.kwargs["document_id"], call.kwargs["content"], at=start)
        resume = pipeline.sync_window_start(self.team, now=NOW)
        assert resume == start + timedelta(hours=1) - pipeline.SYNC_RESUME_OVERLAP

        second = pipeline.run_sync(self.team, window_start=resume, window_end=NOW, budget=100, page_size=1)

        assert second.status == "succeeded"
        assert MCPIntentClusteringRun.objects.get(run_id=second.run_id).window_end == NOW
        emitted = [call.kwargs["document_id"] for call in mock_emit.call_args_list]
        assert sorted(emitted) == sorted(intent_hash(t) for t in ("a", "b", "c", "d"))

    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_one_hour_over_the_budget_is_still_drained_whole(self, mock_emit) -> None:
        start = NOW - timedelta(hours=1)
        for text in ("a", "b", "c"):
            self._call(text, start + timedelta(minutes=10))
        flush_persons_and_events()

        outcome = pipeline.run_sync(self.team, window_start=start, window_end=NOW, budget=1, page_size=1)

        assert (outcome.status, outcome.n_intents, outcome.n_embeddings_requested) == ("succeeded", 3, 3)
        assert MCPIntentClusteringRun.objects.get(run_id=outcome.run_id).window_end == NOW

    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_each_environment_resumes_from_its_own_syncs(self, _mock_emit) -> None:
        sibling = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Sibling"
        )
        sibling_end = NOW - timedelta(hours=5)

        pipeline.run_sync(sibling, window_start=sibling_end - timedelta(hours=1), window_end=sibling_end)
        pipeline.run_sync(self.team, window_start=NOW - timedelta(hours=1), window_end=NOW)

        assert pipeline.sync_window_start(sibling, now=NOW) == sibling_end - pipeline.SYNC_RESUME_OVERLAP
        assert pipeline.sync_window_start(self.team, now=NOW) == NOW - pipeline.SYNC_RESUME_OVERLAP

    @patch("products.mcp_analytics.backend.intent_topics.embedding_sync.emit_embedding_request")
    def test_skips_without_consent(self, mock_emit) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        outcome = pipeline.run_sync(self.team, window_start=NOW - timedelta(hours=1), window_end=NOW)

        assert outcome.status == "skipped_no_consent"
        mock_emit.assert_not_called()


@skip_without_umap
class TestRefitThenAssign(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        for i, vector in enumerate(_blob_vectors(0, 60, seed=1)):
            insert_intent_embedding(
                self.team.pk,
                f"a{i:03d}",
                f"create insight {i}",
                at=NOW - timedelta(days=2),
                embedding=vector,
                calls=1 + i % 3,
            )
        for i, vector in enumerate(_blob_vectors(1, 60, seed=2)):
            insert_intent_embedding(
                self.team.pk, f"b{i:03d}", f"list flags {i}", at=NOW - timedelta(days=3), embedding=vector
            )
        rollups.insert_hourly_calls(
            self.team.pk,
            [
                HourlyCalls(
                    hour=NOW - timedelta(days=2), hash=f"a{i:03d}", tool="query-trends", calls=2, conversations=(1,)
                )
                for i in range(60)
            ]
            + [
                HourlyCalls(
                    hour=NOW - timedelta(days=3),
                    hash=f"b{i:03d}",
                    tool="feature-flag-get-all",
                    calls=1,
                    conversations=(1,),
                )
                for i in range(60)
            ],
            now=NOW,
        )

    def _assignments(self) -> list[tuple]:
        return execute_hogql_query(
            query="SELECT topic_id, count(), countIf(is_outlier = 1) FROM posthog.mcp_intent_assignments GROUP BY topic_id ORDER BY count() DESC",
            team=self.team,
        ).results

    @patch("products.mcp_analytics.backend.intent_topics.pipeline.labeling.label_topics")
    def test_refit_creates_labelled_topics_and_assign_fills_the_table(self, mock_labels) -> None:
        mock_labels.side_effect = lambda team, candidates: {
            c.topic_id: TopicLabel(label=f"Label {i}", summary=f"Summary {i}") for i, c in enumerate(candidates)
        }

        refit = pipeline.run_refit(self.team, now=NOW)

        assert refit.status == "succeeded"
        assert refit.n_topics == 2
        topics = list(MCPIntentTopic.active.filter(team=self.team))
        assert sorted(t.label for t in topics) == ["Label 0", "Label 1"]
        assert all(t.member_count == 60 for t in topics)
        candidates = mock_labels.call_args.args[1]
        assert all(len(c.sample_intents) == 10 for c in candidates)

        assign = pipeline.run_assign(self.team, window_start=NOW - timedelta(days=7), window_end=NOW)

        assert assign.status == "succeeded"
        assert assign.n_intents == 120
        rows = self._assignments()
        assert sorted(r[0] for r in rows) == sorted(str(t.pk) for t in topics)
        assert [r[1] for r in rows] == [60, 60]
        daily = execute_hogql_query(
            query="SELECT topic_id, sum(calls), sum(intents) FROM posthog.mcp_intent_topic_daily GROUP BY topic_id ORDER BY sum(calls) DESC",
            team=self.team,
        ).results
        assert [(r[1], r[2]) for r in daily] == [(120, 60), (60, 60)]

    @patch("products.mcp_analytics.backend.intent_topics.pipeline.labeling.label_topics", return_value={})
    def test_second_refit_keeps_topic_ids(self, _mock_labels) -> None:
        pipeline.run_refit(self.team, now=NOW)
        first_ids = sorted(str(t.pk) for t in MCPIntentTopic.active.filter(team=self.team))

        pipeline.run_refit(self.team, now=NOW + timedelta(hours=1))

        assert sorted(str(t.pk) for t in MCPIntentTopic.active.filter(team=self.team)) == first_ids
        assert MCPIntentClusteringRun.objects.filter(team=self.team, kind="refit", status="succeeded").count() == 2

    def test_assign_without_topics_is_skipped_and_still_counts_the_calls_as_unassigned(self) -> None:
        rollups.insert_hourly_calls(
            self.team.pk,
            [HourlyCalls(hour=NOW - timedelta(hours=3), hash="h1", tool="query-trends", calls=6, conversations=(1,))],
            now=NOW,
        )

        outcome = pipeline.run_assign(self.team, window_start=NOW - timedelta(days=1), window_end=NOW)

        assert outcome.status == "skipped_too_few"
        coverage = (
            MCPIntentTopicsQueryRunner(
                query=MCPIntentTopicsQuery(dateRange=DateRange(date_from=(NOW - timedelta(days=1)).date().isoformat())),
                team=self.team,
            )
            .calculate()
            .coverage
        )
        assert (coverage.calls_with_intent, coverage.calls_assigned) == (6, 0)


class TestRefitTooFew(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def test_skips_when_the_window_has_too_few_vectors(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        insert_intent_embedding(self.team.pk, "only", "only one", at=NOW - timedelta(days=1))
        rollups.insert_hourly_calls(
            self.team.pk,
            [HourlyCalls(hour=NOW - timedelta(days=1), hash="only", tool="query-trends", calls=1, conversations=(1,))],
            now=NOW,
        )

        outcome = pipeline.run_refit(self.team, now=NOW)

        assert outcome.status == "skipped_too_few"
        assert outcome.n_intents == 1


class TestSyncWindow(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def _succeeded_sync(self, window_end, status=MCPIntentClusteringRun.Status.SUCCEEDED) -> None:
        MCPIntentClusteringRun.objects.create(
            team=self.team,
            run_id=f"sync-{window_end.isoformat()}",
            kind="sync",
            status=status,
            window_start=window_end - timedelta(hours=1),
            window_end=window_end,
            params={persist.SOURCE_TEAM_PARAM: self.team.pk},
        )

    def test_first_run_covers_the_default_window(self) -> None:
        start = pipeline.sync_window_start(self.team, now=NOW)

        assert start == NOW - pipeline.DEFAULT_SYNC_LOOKBACK

    def test_resumes_from_the_last_successful_sync_after_missed_runs(self) -> None:
        self._succeeded_sync(NOW - timedelta(hours=5))
        self._succeeded_sync(NOW - timedelta(hours=3), status=MCPIntentClusteringRun.Status.FAILED)

        start = pipeline.sync_window_start(self.team, now=NOW)

        assert start == NOW - timedelta(hours=5) - pipeline.SYNC_RESUME_OVERLAP

    def test_catch_up_is_bounded(self) -> None:
        self._succeeded_sync(NOW - timedelta(days=10))

        start = pipeline.sync_window_start(self.team, now=NOW)

        assert start == NOW - pipeline.MAX_SYNC_CATCH_UP


class TestFitSampleWindow(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def test_sample_follows_calls_in_the_window_not_embedding_time(self) -> None:
        insert_intent_embedding(self.team.pk, "old-but-hot", "old but hot", at=NOW - timedelta(days=20), calls=1)
        insert_intent_embedding(self.team.pk, "fresh-but-cold", "fresh but cold", at=NOW - timedelta(days=1), calls=99)
        insert_intent_embedding(self.team.pk, "expired", "expired", at=NOW - timedelta(days=40), calls=1)
        rollups.insert_hourly_calls(
            self.team.pk,
            [
                HourlyCalls(
                    hour=NOW - timedelta(days=2),
                    hash="old-but-hot",
                    tool="query-trends",
                    calls=40,
                    conversations=(1, 2, 3),
                ),
                HourlyCalls(
                    hour=NOW - timedelta(days=2), hash="expired", tool="query-trends", calls=5, conversations=(1,)
                ),
                HourlyCalls(
                    hour=NOW - timedelta(days=12),
                    hash="fresh-but-cold",
                    tool="query-trends",
                    calls=7,
                    conversations=(1,),
                ),
            ],
            now=NOW,
        )
        # An older version of the same hour bucket must not add to the weight.
        rollups.insert_hourly_calls(
            self.team.pk,
            [
                HourlyCalls(
                    hour=NOW - timedelta(days=2), hash="old-but-hot", tool="query-trends", calls=30, conversations=(1,)
                )
            ],
            now=NOW - timedelta(days=1),
        )
        # Another team's vector for an intent this team calls, and its calls for an intent this team embedded.
        other_team_id = 10**9
        insert_intent_embedding(other_team_id, "shared", "shared", at=NOW - timedelta(days=1))
        rollups.insert_hourly_calls(
            self.team.pk,
            [
                HourlyCalls(
                    hour=NOW - timedelta(days=2), hash="shared", tool="query-trends", calls=50, conversations=(1,)
                )
            ],
            now=NOW,
        )
        rollups.insert_hourly_calls(
            other_team_id,
            [
                HourlyCalls(
                    hour=NOW - timedelta(days=2),
                    hash="fresh-but-cold",
                    tool="query-trends",
                    calls=99,
                    conversations=(1,),
                )
            ],
            now=NOW,
        )

        sample = pipeline.fetch_fit_sample(self.team, since=NOW - timedelta(days=7), until=NOW)

        assert sample.hashes == ["old-but-hot"]
        assert sample.weights.tolist() == [40.0]
