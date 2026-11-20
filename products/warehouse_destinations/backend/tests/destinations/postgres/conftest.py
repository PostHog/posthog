import uuid
from collections.abc import Iterator

import pytest

from django.conf import settings

import psycopg
from psycopg import sql

TEST_DATABASE = "warehouse_destinations_test"


@pytest.fixture(scope="session")
def postgres_config() -> dict[str, str | int]:
    config: dict[str, str | int] = {
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "host": settings.PG_HOST,
        "port": int(settings.PG_PORT),
        "database": TEST_DATABASE,
    }
    with psycopg.connect(
        user=settings.PG_USER,
        password=settings.PG_PASSWORD,
        host=settings.PG_HOST,
        port=int(settings.PG_PORT),
        dbname="postgres",
        autocommit=True,
    ) as connection:
        if connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DATABASE,)).fetchone() is None:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DATABASE)))
    return config


@pytest.fixture
def pg(postgres_config: dict[str, str | int]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        user=str(postgres_config["user"]),
        password=str(postgres_config["password"]),
        host=str(postgres_config["host"]),
        port=int(postgres_config["port"]),
        dbname=TEST_DATABASE,
        autocommit=True,
    ) as connection:
        yield connection


@pytest.fixture
def schema(pg: psycopg.Connection) -> Iterator[str]:
    name = f"wd_test_{uuid.uuid4().hex[:12]}"
    yield name
    pg.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


LIMITED_ROLE = "wd_test_limited"
SLOW_ROLE = "wd_test_slow"
ROLE_PASSWORD = "wd-test-password"


@pytest.fixture(scope="session")
def test_roles(postgres_config: dict[str, str | int]) -> dict[str, str]:
    """Login roles for error tests: one without privileges, one with a short statement timeout."""
    with psycopg.connect(
        user=str(postgres_config["user"]),
        password=str(postgres_config["password"]),
        host=str(postgres_config["host"]),
        port=int(postgres_config["port"]),
        dbname=TEST_DATABASE,
        autocommit=True,
    ) as connection:
        for role in (LIMITED_ROLE, SLOW_ROLE):
            if connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone() is None:
                connection.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(ROLE_PASSWORD))
                )
        connection.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '300ms'").format(sql.Identifier(SLOW_ROLE)))
    return {"limited": LIMITED_ROLE, "slow": SLOW_ROLE}
