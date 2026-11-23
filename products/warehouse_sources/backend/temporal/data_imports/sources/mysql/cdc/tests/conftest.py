from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import pymysql
from testcontainers.mysql import MySqlContainer

ROOT_PASSWORD = "root-test-password"
CDC_USER = "posthog_cdc"
CDC_PASSWORD = "cdc-test-password"
DATABASE = "app"


@pytest.fixture(scope="session")
def mysql_server() -> Iterator[MySqlContainer]:
    container = (
        MySqlContainer("mysql:8.0", root_password=ROOT_PASSWORD, dbname=DATABASE)
        .with_env("MYSQL_INITDB_SKIP_TZINFO", "1")
        .with_command("--binlog-row-metadata=FULL --server-id=1")
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


def connect(server: MySqlContainer, user: str = "root", password: str = ROOT_PASSWORD) -> pymysql.Connection:
    return pymysql.connect(
        host=server.get_container_host_ip(),
        port=int(server.get_exposed_port(3306)),
        user=user,
        password=password,
        autocommit=True,
    )


@pytest.fixture
def root_conn(mysql_server: MySqlContainer) -> Iterator[pymysql.Connection]:
    conn = connect(mysql_server)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def global_variable(conn: pymysql.Connection, name: str, value: str | int) -> Iterator[None]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT @@GLOBAL.{name}")
        (previous,) = cur.fetchone()
        cur.execute(f"SET GLOBAL {name} = %s", (value,))
    try:
        yield
    finally:
        with conn.cursor() as cur:
            cur.execute(f"SET GLOBAL {name} = %s", (previous,))


@contextmanager
def cdc_user(conn: pymysql.Connection, grants: str) -> Iterator[None]:
    with conn.cursor() as cur:
        cur.execute(f"CREATE USER '{CDC_USER}'@'%' IDENTIFIED BY '{CDC_PASSWORD}'")
        cur.execute(f"GRANT SELECT ON {DATABASE}.* TO '{CDC_USER}'@'%'")
        if grants:
            cur.execute(f"GRANT {grants} ON *.* TO '{CDC_USER}'@'%'")
    try:
        yield
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP USER '{CDC_USER}'@'%'")
