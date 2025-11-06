import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import call, patch

from posthog.clickhouse.client import sync_execute

from products.enterprise.backend.clickhouse.materialized_columns.analyze import materialize_properties_task


class TestMaterializedColumnsAnalyze(ClickhouseTestMixin, BaseTest):
    @pytest.mark.skip(reason="Test is failing for some reason")
    @patch("ee.clickhouse.materialized_columns.analyze.materialize")
    @patch("ee.clickhouse.materialized_columns.analyze.backfill_materialized_columns")
    def test_mat_columns(self, patch_backfill, patch_materialize):
        sync_execute("SYSTEM FLUSH LOGS")
        sync_execute("TRUNCATE TABLE system.query_log")

        queries_to_insert = [
            "SELECT * FROM events WHERE JSONExtractRaw(properties, \\'materialize_me\\')",
            "SELECT * FROM events WHERE JSONExtractRaw(properties, \\'materialize_me\\')",
            "SELECT * FROM events WHERE JSONExtractRaw(properties, \\'materialize_me2\\')",
            "SELECT * FROM events WHERE JSONExtractRaw(`e`.properties, \\'materialize_me3\\')",
            "SELECT * FROM events WHERE JSONExtractRaw(person_properties, \\'materialize_person_prop\\')",
            "SELECT * FROM groups WHERE JSONExtractRaw(group.group_properties, \\'materialize_person_prop\\')",  # this should not appear
            "SELECT * FROM groups WHERE JSONExtractRaw(group.group_properties, \\'nested\\', \\'property\\')",  # this should not appear
        ]

        for query in queries_to_insert:
            sync_execute(
                """
            INSERT INTO system.query_log (
                query,
                query_start_time,
                type,
                is_initial_query,
                log_comment,
                exception_code,
                read_bytes,
                read_rows
            ) VALUES (
                '{query}',
                now(),
                3,
                1,
                '{log_comment}',
                159,
                40000000000,
                10000000
            )
            """.format(query=query, log_comment='{"team_id": 2}')
            )
        materialize_properties_task()
        patch_materialize.assert_has_calls(
            [
                call("events", "materialize_me", table_column="properties", is_nullable=False),
                call("events", "materialize_me2", table_column="properties", is_nullable=False),
                call("events", "materialize_person_prop", table_column="person_properties", is_nullable=False),
                call("events", "materialize_me3", table_column="properties", is_nullable=False),
            ]
        )
