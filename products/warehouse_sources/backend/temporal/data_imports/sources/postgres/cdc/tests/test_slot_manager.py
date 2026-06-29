import datetime as dt
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock
from unittest.mock import MagicMock

import psycopg.errors
from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.slot_manager import (
    add_table_to_publication,
    cdc_pg_connection,
    get_max_slot_wal_keep_size_mb,
    get_publication_tables,
    is_slot_invalidation_error,
    remove_table_from_publication,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import SSL_REQUIRED_AFTER_DATE


def _mock_conn(execute_side_effect=None):
    """Create a mock psycopg connection with a context-manager cursor."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.commit = MagicMock()
    conn.rollback = MagicMock()

    if execute_side_effect is not None:
        cursor.execute.side_effect = execute_side_effect

    return conn, cursor


class TestAddTableToPublication:
    def test_add_table_success(self):
        conn, cursor = _mock_conn()

        add_table_to_publication(conn, pub_name="my_pub", schema="public", table="users")

        cursor.execute.assert_called_once()
        sql_str = str(cursor.execute.call_args[0][0])
        assert "ALTER PUBLICATION" in sql_str
        assert "ADD TABLE" in sql_str
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_add_table_duplicate_is_noop(self):
        conn, cursor = _mock_conn(execute_side_effect=psycopg.errors.DuplicateObject())

        add_table_to_publication(conn, pub_name="my_pub", schema="public", table="users")

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()


class TestIsSlotInvalidationError:
    @parameterized.expand(
        [
            (
                "invalidated_max_reserved_size",
                psycopg.errors.ObjectNotInPrerequisiteState(
                    'can no longer get changes from replication slot "posthog_019e51352190"\n'
                    "DETAIL:  This slot has been invalidated because it exceeded the maximum reserved size."
                ),
                True,
            ),
            (
                "invalidated_pg17_wording",
                psycopg.errors.ObjectNotInPrerequisiteState(
                    'This replication slot has been invalidated due to "wal_removed".'
                ),
                True,
            ),
            (
                "advance_on_invalidated_slot",
                psycopg.errors.ObjectNotInPrerequisiteState(
                    "cannot advance replication slot that has not previously reserved WAL"
                ),
                True,
            ),
            (
                "slot_dropped",
                psycopg.errors.UndefinedObject('replication slot "posthog_019e51352190" does not exist'),
                True,
            ),
            (
                "publication_missing_is_not_slot_loss",
                psycopg.errors.UndefinedObject('publication "posthog_pub" does not exist'),
                False,
            ),
            (
                "other_prerequisite_error",
                psycopg.errors.ObjectNotInPrerequisiteState("logical decoding requires wal_level >= logical"),
                False,
            ),
            ("unrelated_error", RuntimeError("connection lost"), False),
        ]
    )
    def test_detection(self, _name, exc, expected):
        assert is_slot_invalidation_error(exc) is expected

    def test_detects_error_in_exception_chain(self):
        cause = psycopg.errors.ObjectNotInPrerequisiteState(
            'can no longer get changes from replication slot "posthog_x"'
        )
        wrapper = RuntimeError("read failed")
        wrapper.__cause__ = cause
        assert is_slot_invalidation_error(wrapper) is True


class TestGetMaxSlotWalKeepSizeMb:
    @parameterized.expand(
        [
            ("configured", (5120,), 5120),
            ("unlimited", (-1,), None),
            ("missing_setting", None, None),
        ]
    )
    def test_parsing(self, _name, row, expected):
        conn, cursor = _mock_conn()
        cursor.fetchone.return_value = row

        assert get_max_slot_wal_keep_size_mb(conn) == expected


class TestGetPublicationTables:
    @parameterized.expand(
        [
            ("with_tables", [("public", "orders"), ("analytics", "events")], ["public.orders", "analytics.events"]),
            ("empty_publication", [], []),
        ]
    )
    def test_returns_schema_qualified_tables(self, _name, fetchall, expected):
        conn, cursor = _mock_conn()
        cursor.fetchall.return_value = fetchall

        assert get_publication_tables(conn, pub_name="my_pub") == expected
        assert "pg_publication_tables" in str(cursor.execute.call_args[0][0])


class TestRemoveTableFromPublication:
    def test_remove_table_success(self):
        conn, cursor = _mock_conn()

        remove_table_from_publication(conn, pub_name="my_pub", schema="public", table="users")

        cursor.execute.assert_called_once()
        sql_str = str(cursor.execute.call_args[0][0])
        assert "ALTER PUBLICATION" in sql_str
        assert "DROP TABLE" in sql_str
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_remove_table_missing_is_noop(self):
        conn, cursor = _mock_conn(execute_side_effect=psycopg.errors.UndefinedTable())

        remove_table_from_publication(conn, pub_name="my_pub", schema="public", table="users")

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()


class TestCdcPgConnectionSsl:
    @pytest.mark.parametrize(
        "is_new_source,ssh_tunnel_enabled,require_tls,expected_require_ssl",
        [
            (True, False, True, True),
            (True, True, True, True),
            (True, True, False, False),
            (False, False, True, False),
        ],
    )
    def test_honors_ssh_tunnel_tls_optout(self, is_new_source, ssh_tunnel_enabled, require_tls, expected_require_ssl):
        # CDC must derive `require_ssl` from the full config like the main pipeline path, so an
        # SSH-tunnel `require_tls` opt-out is honored. Otherwise SSL is forced on and a database
        # reached over an SSH tunnel that doesn't speak SSL fails with "server does not support SSL".
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

        config = PostgresSource().parse_config(
            {
                "host": "db.example.com",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "public",
            }
        )
        if ssh_tunnel_enabled:
            config.ssh_tunnel = mock.MagicMock(enabled=True, require_tls=mock.MagicMock(enabled=require_tls))
        else:
            config.ssh_tunnel = None

        created_at = (
            SSL_REQUIRED_AFTER_DATE + dt.timedelta(days=1)
            if is_new_source
            else SSL_REQUIRED_AFTER_DATE - dt.timedelta(days=1)
        )
        source = SimpleNamespace(job_inputs={}, created_at=created_at)

        @contextmanager
        def fake_tunnel(self, config):
            yield ("127.0.0.1", 44549)

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.parse_config",
                return_value=config,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.with_ssh_tunnel",
                fake_tunnel,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._connect_to_postgres"
            ) as mock_connect,
        ):
            with cdc_pg_connection(cast(ExternalDataSource, source)):
                pass

        mock_connect.assert_called_once()
        assert mock_connect.call_args.kwargs["require_ssl"] is expected_require_ssl
