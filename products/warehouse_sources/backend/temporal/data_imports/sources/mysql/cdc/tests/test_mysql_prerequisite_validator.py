import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.prerequisite_validator import (
    validate_cdc_prerequisites,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.tests.conftest import (
    CDC_PASSWORD,
    CDC_USER,
    DATABASE,
    UNLOGGED_DATABASE,
    cdc_user,
    connect,
    global_variable,
)

_ALL_GRANTS = "REPLICATION SLAVE, REPLICATION CLIENT, PROCESS"


@pytest.fixture(autouse=True)
def tables(root_conn):
    with root_conn.cursor() as cur:
        cur.execute(f"CREATE TABLE {DATABASE}.keyed (id INT PRIMARY KEY, name TEXT)")
        cur.execute(f"CREATE TABLE {DATABASE}.unkeyed (name TEXT)")
    yield
    with root_conn.cursor() as cur:
        cur.execute(f"DROP TABLE {DATABASE}.keyed, {DATABASE}.unkeyed")


class TestValidateCDCPrerequisites:
    def _validate(
        self, mysql_server, tables=("keyed",), database=DATABASE, grants=_ALL_GRANTS, role_grants=None
    ) -> list[str]:
        root = connect(mysql_server)
        try:
            with cdc_user(root, grants):
                if role_grants:
                    with root.cursor() as cur:
                        cur.execute("CREATE ROLE IF NOT EXISTS 'cdc_reader'")
                        cur.execute(f"GRANT {role_grants} ON *.* TO 'cdc_reader'")
                        cur.execute(f"GRANT 'cdc_reader' TO '{CDC_USER}'@'%'")
                        cur.execute(f"SET DEFAULT ROLE 'cdc_reader' TO '{CDC_USER}'@'%'")
                conn = connect(mysql_server, CDC_USER, CDC_PASSWORD)
                try:
                    return validate_cdc_prerequisites(conn, tables=list(tables), database=database)
                finally:
                    conn.close()
        finally:
            root.close()

    def test_ready_server_passes(self, mysql_server):
        assert self._validate(mysql_server, tables=(f"{DATABASE}.keyed",), database=None) == []

    @pytest.mark.parametrize(
        "variable,value,expected",
        [
            ("binlog_format", "STATEMENT", "binlog_format is STATEMENT"),
            ("binlog_row_image", "MINIMAL", "binlog_row_image is MINIMAL"),
            ("binlog_row_metadata", "MINIMAL", "binlog_row_metadata is MINIMAL"),
            ("binlog_expire_logs_seconds", 3600, "keeps binary logs for 1 hours"),
            ("binlog_transaction_compression", "ON", "binlog_transaction_compression is ON"),
            ("binlog_row_value_options", "PARTIAL_JSON", "binlog_row_value_options is PARTIAL_JSON"),
        ],
    )
    def test_misconfigured_binlog_setting_is_reported(self, mysql_server, root_conn, variable, value, expected):
        with global_variable(root_conn, variable, value):
            [error] = self._validate(mysql_server)
        assert expected in error

    def test_missing_replication_grants_are_named(self, mysql_server):
        [error] = self._validate(mysql_server, grants="REPLICATION CLIENT")
        assert "missing REPLICATION SLAVE, PROCESS" in error

    def test_table_without_primary_key_is_named(self, mysql_server):
        [error] = self._validate(mysql_server, tables=("keyed", "unkeyed"))
        assert f"{DATABASE}.unkeyed" in error
        assert f"{DATABASE}.keyed," not in error

    def test_grants_held_through_a_default_role_pass(self, mysql_server):
        assert self._validate(mysql_server, grants="", role_grants=_ALL_GRANTS) == []

    def test_database_left_out_of_the_binlog_is_named(self, mysql_server, root_conn):
        with root_conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE {UNLOGGED_DATABASE}")
            cur.execute(f"CREATE TABLE {UNLOGGED_DATABASE}.keyed (id INT PRIMARY KEY)")
        try:
            errors = self._validate(
                mysql_server, tables=(f"{UNLOGGED_DATABASE}.keyed", f"{DATABASE}.keyed"), database=None
            )
        finally:
            with root_conn.cursor() as cur:
                cur.execute(f"DROP DATABASE {UNLOGGED_DATABASE}")
        [error] = [error for error in errors if "out of the binary log" in error]
        assert error.endswith(
            f"databases out of the binary log, so their changes can't be captured: {UNLOGGED_DATABASE}. Remove them from binlog-ignore-db, or add them to binlog-do-db."
        )
