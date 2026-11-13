import os

os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")

from datetime import timedelta  # noqa: E402

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events  # noqa: E402
from unittest.mock import patch  # noqa: E402

import numpy as np  # noqa: E402

from posthog.hogql.query import execute_hogql_query  # noqa: E402

from products.mcp_analytics.backend.intent_hash import intent_hash  # noqa: E402
from products.mcp_analytics.backend.intent_topics import pipeline  # noqa: E402
from products.mcp_analytics.backend.intent_topics.labeling import TopicLabel  # noqa: E402
from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentTopic  # noqa: E402
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin  # noqa: E402
from products.mcp_analytics.backend.tests.intent_topics_helpers import insert_intent_embedding, recent_hour
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

    @patch("products.mcp_analytics.backend.intent_topics.pipeline.labeling.label_topics", return_value={})
    def test_second_refit_keeps_topic_ids(self, _mock_labels) -> None:
        pipeline.run_refit(self.team, now=NOW)
        first_ids = sorted(str(t.pk) for t in MCPIntentTopic.active.filter(team=self.team))

        pipeline.run_refit(self.team, now=NOW + timedelta(hours=1))

        assert sorted(str(t.pk) for t in MCPIntentTopic.active.filter(team=self.team)) == first_ids
        assert MCPIntentClusteringRun.objects.filter(team=self.team, kind="refit", status="succeeded").count() == 2

    def test_assign_without_topics_is_skipped(self) -> None:
        outcome = pipeline.run_assign(self.team, window_start=NOW - timedelta(days=1), window_end=NOW)

        assert outcome.status == "skipped_too_few"


class TestRefitTooFew(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def test_skips_when_the_window_has_too_few_vectors(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        insert_intent_embedding(self.team.pk, "only", "only one", at=NOW - timedelta(days=1))

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
