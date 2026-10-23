import re
import importlib
from types import ModuleType

from unittest import mock

from parameterized import parameterized

from products.error_tracking.backend.indexed_embedding import (
    DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL,
    EMBEDDING_TABLES,
    EMBEDDING_TABLES_1,
    EMBEDDING_TABLES_2,
    SMALL_256_MODEL_NAME,
    ModelTableDefinitions,
)

MIGRATION_0360 = "posthog.clickhouse.migrations.0360_embedding_model_small_256"


def _migration_statements(module_name: str, cloud_deployment: str) -> list[str]:
    module: ModuleType = importlib.import_module(module_name)
    try:
        with mock.patch("posthog.settings.CLOUD_DEPLOYMENT", cloud_deployment):
            module = importlib.reload(module)
            return [op._sql for op in module.operations]
    finally:
        importlib.reload(module)


def _mv_source_and_target(statements: list[str], mv_name: str) -> list[tuple[int, str, str]]:
    found = []
    for position, sql in enumerate(statements):
        match = re.search(
            rf"CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}\s+TO (\S+).*FROM \S+?\.(\S+)", sql, re.DOTALL
        )
        if match:
            found.append((position, match.group(1), match.group(2)))
    return found


def _table(model_name: str) -> ModelTableDefinitions:
    matches = [table for table in EMBEDDING_TABLES if table.model_name == model_name]
    assert len(matches) == 1, f"expected exactly one table for {model_name}"
    return matches[0]


class TestSmall256Table:
    def test_is_registered_with_dimension_256(self):
        table = _table(SMALL_256_MODEL_NAME)
        assert table.dimension == 256
        assert table in EMBEDDING_TABLES_2
        assert table.sharded_table_name() == "sharded_posthog_document_embeddings_text_embedding_3_small_256"

    def test_keeps_rows_for_one_month(self):
        sql = _table(SMALL_256_MODEL_NAME).sharded_table_sql()
        assert "TTL timestamp + INTERVAL 1 MONTH" in sql
        assert "INTERVAL 3 MONTH" not in sql
        assert "CHECK length(embedding) = 256" in sql

    def test_has_no_vector_index(self):
        assert _table(SMALL_256_MODEL_NAME).add_vector_index_sql() == []

    def test_is_part_of_the_union_view(self):
        sql = DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL()
        assert f"'{SMALL_256_MODEL_NAME}' AS model_name" in sql
        assert "FROM distributed_posthog_document_embeddings_text_embedding_3_small_256" in sql


class TestExistingTablesUnchanged:
    def test_first_generation_tables_keep_three_months_and_indexes(self):
        for table in EMBEDDING_TABLES_1:
            sql = table.sharded_table_sql()
            assert "TTL timestamp + INTERVAL 3 MONTH" in sql
            index_sql = table.add_vector_index_sql()
            assert len(index_sql) == 2
            assert all("vector_similarity('hnsw'" in statement for statement in index_sql)

    def test_dimension_still_parses_from_model_name(self):
        assert ModelTableDefinitions("text-embedding-3-small-1536").dimension == 1536


class TestMigrationReplay:
    def test_union_view_can_be_built_from_a_fixed_model_set(self):
        # 0191 runs on a fresh database before the 256 table exists, so it must not reference it.
        sql = DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL(EMBEDDING_TABLES_1)
        assert "text_embedding_3_small_256" not in sql
        assert "distributed_posthog_document_embeddings_text_embedding_3_small_1536" in sql
        assert "distributed_posthog_document_embeddings_text_embedding_3_large_3072" in sql

    def test_migration_0191_builds_the_view_from_the_first_model_set(self):
        import importlib

        migration = importlib.import_module("posthog.clickhouse.migrations.0191_model_specific_embedding_tables")
        statements = [op._sql for op in migration.operations]
        view_sql = [
            sql for sql in statements if "CREATE VIEW IF NOT EXISTS posthog_document_embeddings_union_view" in sql
        ]
        assert len(view_sql) == 1
        assert all("text_embedding_3_small_256" not in sql for sql in statements)

    @parameterized.expand(["", "US", "EU", "DEV"])
    def test_migration_0360_replaces_the_union_view_without_dropping_it(self, cloud_deployment):
        statements = _migration_statements(MIGRATION_0360, cloud_deployment)
        assert not any(re.search(r"DROP VIEW", sql) for sql in statements)
        view_sql = [sql for sql in statements if "posthog_document_embeddings_union_view" in sql]
        assert len(view_sql) == 1
        assert view_sql[0].startswith("CREATE OR REPLACE VIEW posthog_document_embeddings_union_view")
        for table in [*EMBEDDING_TABLES_1, *EMBEDDING_TABLES_2]:
            assert f"FROM {table.distributed_table_name()}" in view_sql[0]

    @parameterized.expand(
        [
            ("hobby_and_local", "", "kafka_posthog_document_embeddings", False),
            ("us", "US", "kafka_posthog_document_embeddings_ws", True),
            ("eu", "EU", "kafka_posthog_document_embeddings_ws", True),
            ("dev", "DEV", "kafka_posthog_document_embeddings_ws", True),
        ]
    )
    def test_migration_0360_resumes_the_buffer_from_the_active_kafka_source(
        self, _name, cloud_deployment, kafka_source, warpstream_consumer_paused
    ):
        statements = _migration_statements(MIGRATION_0360, cloud_deployment)
        model_mv_positions = [
            position
            for position, sql in enumerate(statements)
            for table in EMBEDDING_TABLES_2
            if sql.strip().startswith(f"CREATE MATERIALIZED VIEW IF NOT EXISTS {table.materialized_view_name()}")
        ]
        assert model_mv_positions

        buffer_mvs = _mv_source_and_target(statements, "posthog_document_embeddings_kafka_to_buffer_mv")
        assert [(target, source) for _, target, source in buffer_mvs] == [
            ("writable_posthog_document_embeddings_buffer", kafka_source)
        ]
        assert buffer_mvs[0][0] > max(model_mv_positions)
        assert statements[0].strip() == "DROP TABLE IF EXISTS posthog_document_embeddings_kafka_to_buffer_mv"

        ws_drops = [
            i
            for i, sql in enumerate(statements)
            if sql.strip() == "DROP TABLE IF EXISTS posthog_document_embeddings_ws_mv"
        ]
        ws_mvs = _mv_source_and_target(statements, "posthog_document_embeddings_ws_mv")
        if warpstream_consumer_paused:
            assert ws_drops and ws_drops[0] < min(model_mv_positions)
            assert [(target, source) for _, target, source in ws_mvs] == [
                ("writable_posthog_document_embeddings", "kafka_posthog_document_embeddings_ws")
            ]
            assert ws_mvs[0][0] > max(model_mv_positions)
        else:
            assert ws_drops == []
            assert ws_mvs == []


class TestResponseSchema:
    def test_embedding_record_accepts_the_256_model(self):
        from posthog.schema import EmbeddingModelName

        assert EmbeddingModelName("text-embedding-3-small-256") == SMALL_256_MODEL_NAME
