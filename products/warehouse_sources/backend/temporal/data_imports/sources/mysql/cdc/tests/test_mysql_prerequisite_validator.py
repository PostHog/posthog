import uuid

import pytest

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.adapter import MySQLCDCAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.prerequisite_validator import (
    time_zone_error,
    validate_cdc_prerequisites,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.tests.conftest import (
    CDC_PASSWORD,
    CDC_USER,
    DATABASE,
    ROOT_PASSWORD,
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

    @pytest.mark.parametrize(
        "grants,missing",
        [
            ("REPLICATION CLIENT", "REPLICATION SLAVE, PROCESS"),
            # Without REPLICATION CLIENT the server refuses to show the binlog's filters.
            ("REPLICATION SLAVE, PROCESS", "REPLICATION CLIENT"),
        ],
    )
    def test_missing_replication_grants_are_named(self, mysql_server, grants, missing):
        [error] = self._validate(mysql_server, grants=grants)
        assert f"missing {missing}." in error

    def test_table_without_primary_key_is_named(self, mysql_server):
        [error] = self._validate(mysql_server, tables=("keyed", "unkeyed"))
        assert f"{DATABASE}.unkeyed" in error
        assert f"{DATABASE}.keyed," not in error

    def test_a_table_that_does_not_exist_is_not_called_unkeyed(self, mysql_server):
        [error] = self._validate(mysql_server, tables=("keyed", "missing"))
        assert error.startswith(f"These tables don't exist on the server: {DATABASE}.missing.")

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


@pytest.mark.django_db
def test_the_adapter_reads_the_database_from_the_source_not_the_view_hint(team, mysql_server):
    source = ExternalDataSource.objects.create(
        team_id=team.pk,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        source_type="MySQL",
        job_inputs={
            "host": mysql_server.get_container_host_ip(),
            "port": int(mysql_server.get_exposed_port(3306)),
            "database": DATABASE,
            "user": "root",
            "password": ROOT_PASSWORD,
            "schema": "",
            "using_ssl": False,
        },
    )

    # A blank schema reads every database, so tables are named database.table, and the view sends "public".
    errors = MySQLCDCAdapter().validate_prerequisites(
        source, management_mode="posthog", tables=[f"{DATABASE}.keyed"], schema="public", setup={}
    )

    assert errors == []


@pytest.mark.parametrize(
    "time_zone,system_time_zone,refused",
    [
        ("SYSTEM", "UTC", False),
        ("SYSTEM", "America/New_York", False),
        ("+02:00", "CEST", False),
        ("SYSTEM", "CEST", True),
        ("SYSTEM", "EST", True),
    ],
)
def test_a_system_time_zone_without_daylight_saving_rules_is_refused(time_zone, system_time_zone, refused):
    assert (time_zone_error(time_zone, system_time_zone) is not None) is refused
