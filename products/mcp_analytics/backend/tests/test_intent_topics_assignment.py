from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute

from products.mcp_analytics.backend.intent_topics.assignment_sql import PcaBasis, TopicVector, build_assignment_insert
from products.mcp_analytics.backend.tests.intent_topics_helpers import insert_intent_embedding, recent_hour, unit_vector

OTHER_TEAM_ID = 10**9  # never a real team in the test database, so rows cannot collide with the next test
DAY_START = recent_hour(days_ago=2).replace(hour=0)
DAY_END = DAY_START + timedelta(days=1)


class TestAssignmentInsert(ClickhouseTestMixin, APIBaseTest):
    def _topics(self) -> list[TopicVector]:
        return [
            TopicVector(topic_id="topic-a", centroid=unit_vector(0), outlier_distance=0.3),
            TopicVector(topic_id="topic-b", centroid=unit_vector(1), outlier_distance=0.3),
        ]

    def _pca(self) -> PcaBasis:
        return PcaBasis(mean=[0.0] * 256, pc1=unit_vector(0), pc2=unit_vector(1))

    def _run(self, team_id: int | None = None) -> None:
        sql, params = build_assignment_insert(
            team_id=team_id or self.team.pk,
            run_id="assign-1",
            window_start=DAY_START,
            window_end=DAY_END,
            topics=self._topics(),
            pca=self._pca(),
        )
        sync_execute(sql, params)

    def _assignments(self) -> list[tuple]:
        response = execute_hogql_query(
            query="""
                SELECT intent_hash, topic_id, is_outlier, round(toFloat(distance), 3), round(toFloat(x), 3), round(toFloat(y), 3),
                       intent_text, calls_in_run, run_id
                FROM posthog.mcp_intent_assignments ORDER BY intent_hash
            """,
            team=self.team,
        )
        return response.results

    def test_assigns_each_intent_to_its_nearest_topic(self) -> None:
        near_a = unit_vector(0)
        near_b = [0.0] * 256
        near_b[1] = 0.9
        near_b[2] = 0.1
        insert_intent_embedding(
            self.team.pk, "h-a", "near a", at=DAY_START + timedelta(hours=3), embedding=near_a, calls=7
        )
        insert_intent_embedding(
            self.team.pk, "h-b", "near b", at=DAY_START + timedelta(hours=4), embedding=near_b, calls=2
        )

        self._run()

        rows = self._assignments()
        assert [(r[0], r[1], r[2]) for r in rows] == [("h-a", "topic-a", 0), ("h-b", "topic-b", 0)]
        assert rows[0][3] == 0.0
        assert rows[0][4:6] == (1.0, 0.0)  # PCA projection of e0 on (pc1=e0, pc2=e1)
        assert rows[0][6:9] == ("near a", 7, "assign-1")

    def test_flags_outliers_beyond_the_topic_distance(self) -> None:
        far = [0.0] * 256
        far[0] = 0.5
        far[5] = 0.5
        far[6] = 0.5
        far[7] = 0.5
        insert_intent_embedding(self.team.pk, "h-far", "far away", at=DAY_START + timedelta(hours=1), embedding=far)

        self._run()

        rows = self._assignments()
        assert [(r[0], r[1], r[2]) for r in rows] == [("h-far", "topic-a", 1)]
        assert rows[0][3] == 0.5

    def test_scopes_to_team_window_and_document_type(self) -> None:
        insert_intent_embedding(self.team.pk, "h-in", "in window", at=DAY_START + timedelta(hours=1))
        insert_intent_embedding(self.team.pk, "h-out", "yesterday", at=DAY_START - timedelta(hours=1))
        insert_intent_embedding(OTHER_TEAM_ID, "h-other", "other team", at=DAY_START + timedelta(hours=1))

        self._run()

        assert [r[0] for r in self._assignments()] == ["h-in"]

    def test_truncates_long_text_and_keeps_one_row_per_hash(self) -> None:
        insert_intent_embedding(self.team.pk, "h-long", "x" * 900, at=DAY_START + timedelta(hours=1))
        insert_intent_embedding(self.team.pk, "h-long", "x" * 900, at=DAY_START + timedelta(hours=2))

        self._run()

        rows = self._assignments()
        assert len(rows) == 1
        assert len(rows[0][6]) == 500

    def test_truncation_never_splits_a_multibyte_character(self) -> None:
        text = "a" * 499 + "é" + "tail"
        insert_intent_embedding(self.team.pk, "h-utf8", text, at=DAY_START + timedelta(hours=1))

        self._run()

        [row] = self._assignments()
        assert row[6] == "a" * 499 + "é"
