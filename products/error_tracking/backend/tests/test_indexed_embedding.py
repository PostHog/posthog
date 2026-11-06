from products.error_tracking.backend.indexed_embedding import (
    DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL,
    EMBEDDING_TABLES,
    EMBEDDING_TABLES_1,
    EMBEDDING_TABLES_2,
    SMALL_256_MODEL_NAME,
    ModelTableDefinitions,
    drop_union_view_sql,
)


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

    def test_union_view_can_be_dropped_before_recreation(self):
        assert drop_union_view_sql() == "DROP VIEW IF EXISTS posthog_document_embeddings_union_view"
        assert (
            "CREATE VIEW IF NOT EXISTS posthog_document_embeddings_union_view" in DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL()
        )

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


class TestResponseSchema:
    def test_embedding_record_accepts_the_256_model(self):
        from posthog.schema import EmbeddingModelName

        assert EmbeddingModelName("text-embedding-3-small-256") == SMALL_256_MODEL_NAME
