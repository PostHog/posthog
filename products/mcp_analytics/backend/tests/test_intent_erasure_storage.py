import json
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import AlterTableMutationRunner
from posthog.dags.tests.conftest import isolated_clickhouse_cluster
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team

from products.error_tracking.backend.facade.api import document_embedding_tables, document_embeddings_buffer_table
from products.mcp_analytics.backend.facade.clickhouse_schema import MCP_INTENT_ASSIGNMENTS_DATA_TABLE
from products.mcp_analytics.backend.facade.contracts import IntentErasure, IntentErasurePending
from products.mcp_analytics.backend.intent_erasure_storage import purge_intent_storage
from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot, MCPIntentEmbeddingCache, MCPSession
from products.mcp_analytics.backend.tests.test_intent_assignments_table import _insert_assignment


def _embedding_tables() -> list[str]:
    return [table.sharded_table for table in document_embedding_tables()] + [document_embeddings_buffer_table()]


def _dimension(table: str) -> int:
    # Each model table checks its vector length, and its name ends in that length. The buffer has no check.
    suffix = table.rsplit("_", 1)[-1]
    return int(suffix) if suffix.isdigit() else 256


class TestPurgeIntentStorage(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cluster = self.enterContext(isolated_clickhouse_cluster())
        self.sibling = Team.objects.create(organization=self.organization, parent_team=self.team)
        self.other = Team.objects.create(organization=self.organization)
        self.erasure = IntentErasure(
            project_id=self.team.pk, invalidation_id=self.team.uuid, source_team_ids=(self.team.pk, self.sibling.pk)
        )

    def _seed(self, team: Team) -> None:
        # The buffer drops rows a day after they are inserted, so seed with the current time.
        now = datetime.now(UTC)
        _insert_assignment(team.pk, "a" * 64, "topic", intent_text="list example flags")
        for table in _embedding_tables():
            sync_execute(
                f"INSERT INTO {table} (team_id, product, document_type, rendering, document_id, timestamp, inserted_at, content, metadata, embedding) VALUES",
                [
                    (
                        team.pk,
                        product,
                        "mcp-intent",
                        "raw",
                        # The buffer collapses rows that share a document id, so each row gets its own.
                        f"{team.pk}-{product}",
                        now,
                        now,
                        "list example flags",
                        json.dumps({}),
                        [0.0] * _dimension(table),
                    )
                    for product in ("mcp_analytics", "error_tracking")
                ],
            )
        # The legacy Postgres copies are stored on the project, so an environment only has ClickHouse copies.
        if team.parent_team_id is not None:
            return
        with team_scope(team.pk, canonical=True):
            MCPSession.objects.create(team=team, session_id=f"session-{team.pk}", intent="list example flags")
            MCPIntentClusterSnapshot.objects.create(team=team, clusters={"clusters": [{"label": "example flags"}]})
            MCPIntentEmbeddingCache.objects.create(team=team, content_hash="a" * 64, model="example", embedding=b"x")

    def _clickhouse_rows(self, team: Team) -> dict[str, int]:
        rows = {
            "assignments": sync_execute(
                f"SELECT count() FROM {MCP_INTENT_ASSIGNMENTS_DATA_TABLE} WHERE team_id = %(team_id)s",
                {"team_id": team.pk},
            )[0][0]
        }
        for table in _embedding_tables():
            for product in ("mcp_analytics", "error_tracking"):
                rows[f"{table}/{product}"] = sync_execute(
                    f"SELECT count() FROM {table} WHERE team_id = %(team_id)s AND product = %(product)s",
                    {"team_id": team.pk, "product": product},
                )[0][0]
        return rows

    def _postgres_copies(self, team: Team) -> tuple[str | None, dict, int]:
        with team_scope(team.pk, canonical=True):
            return (
                MCPSession.objects.get(team=team).intent,
                MCPIntentClusterSnapshot.objects.get(team=team).clusters,
                MCPIntentEmbeddingCache.objects.filter(team=team).count(),
            )

    def test_purges_every_intent_copy_of_the_project_and_nothing_else(self) -> None:
        for team in (self.team, self.sibling, self.other):
            self._seed(team)

        purge_intent_storage(erasure=self.erasure, cluster=self.cluster)

        for team in (self.team, self.sibling):
            rows = self._clickhouse_rows(team)
            # Other products embed into the same tables; their documents stay.
            assert {key: count for key, count in rows.items() if count} == {
                f"{table}/error_tracking": 1 for table in _embedding_tables()
            }
        other = self._clickhouse_rows(self.other)
        assert {key: count for key, count in other.items() if count != 1} == {}
        assert self._postgres_copies(self.team) == (None, {}, 0)
        assert self._postgres_copies(self.other) == (
            "list example flags",
            {"clusters": [{"label": "example flags"}]},
            1,
        )

    def test_a_delete_that_never_reaches_the_rows_keeps_the_erasure_pending(self) -> None:
        self._seed(self.sibling)

        with (
            patch.object(AlterTableMutationRunner, "run_on_shards"),
            self.assertRaisesMessage(IntentErasurePending, "survived the purge"),
        ):
            purge_intent_storage(erasure=self.erasure, cluster=self.cluster)
