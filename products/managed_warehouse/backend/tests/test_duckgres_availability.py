from typing import Any

import pytest
from unittest.mock import MagicMock

from django.core.cache import cache

import psycopg

from products.managed_warehouse.backend import duckgres_availability
from products.managed_warehouse.backend.duckgres_availability import (
    DuckgresOrganizationStatus,
    probe_duckgres_organization,
)

MANAGED_HOST = "org-1.dw.us.example.com"
REFUSAL = (
    "connection failed: FATAL:  this server requires connecting via "
    "<org-id>.dw.us.example.com or <org-id>.dw.eu.example.com"
)


@pytest.fixture(autouse=True)
def _fresh_probe_state(monkeypatch):
    cache.clear()
    monkeypatch.setattr(duckgres_availability, "is_dev_mode", lambda: False)
    yield
    cache.clear()


def _server(host: str = MANAGED_HOST) -> Any:
    return MagicMock(host=host, organization_id="org-1")


@pytest.mark.parametrize(
    "_name, error, expected",
    [
        ("connects", None, DuckgresOrganizationStatus.AVAILABLE),
        ("refuses_a_managed_host", psycopg.OperationalError(REFUSAL), DuckgresOrganizationStatus.REFUSED),
        (
            "times_out",
            psycopg.errors.ConnectionTimeout("connection timeout expired"),
            DuckgresOrganizationStatus.UNKNOWN,
        ),
        (
            "fails_to_authenticate",
            psycopg.OperationalError("password authentication failed"),
            DuckgresOrganizationStatus.UNKNOWN,
        ),
        ("fails_with_a_non_database_error", OSError("network unreachable"), DuckgresOrganizationStatus.UNKNOWN),
    ],
)
def test_probe_classifies_how_duckgres_answers(_name, error, expected, monkeypatch) -> None:
    connect = MagicMock(side_effect=error)
    monkeypatch.setattr(duckgres_availability, "connect_to_duckgres", connect)

    assert probe_duckgres_organization(_server()) is expected

    assert connect.call_args.kwargs["application_name"] == "ducklake-register-probe"
    assert connect.call_args.kwargs["connect_timeout"] == 15


def test_probe_treats_a_refusal_for_a_host_that_is_not_managed_as_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        duckgres_availability, "connect_to_duckgres", MagicMock(side_effect=psycopg.OperationalError(REFUSAL))
    )

    assert probe_duckgres_organization(_server("10.0.0.5")) is DuckgresOrganizationStatus.UNKNOWN


def test_probe_closes_the_connection_it_opens(monkeypatch) -> None:
    connection = MagicMock()
    monkeypatch.setattr(duckgres_availability, "connect_to_duckgres", MagicMock(return_value=connection))

    probe_duckgres_organization(_server())

    connection.close.assert_called_once_with()


@pytest.mark.parametrize(
    "_name, error, expected, ttl",
    [
        ("available", None, DuckgresOrganizationStatus.AVAILABLE, 24 * 60 * 60),
        ("refused", psycopg.OperationalError(REFUSAL), DuckgresOrganizationStatus.REFUSED, 10 * 60),
        (
            "unknown",
            psycopg.errors.ConnectionTimeout("connection timeout expired"),
            DuckgresOrganizationStatus.UNKNOWN,
            60 * 60,
        ),
    ],
)
def test_probe_caches_each_answer_for_its_own_time(_name, error, expected, ttl, monkeypatch) -> None:
    connect = MagicMock(side_effect=error)
    monkeypatch.setattr(duckgres_availability, "connect_to_duckgres", connect)
    spy = MagicMock(wraps=cache)
    monkeypatch.setattr(duckgres_availability, "cache", spy)

    assert probe_duckgres_organization(_server()) is expected
    assert probe_duckgres_organization(_server()) is expected

    assert connect.call_count == 1
    assert spy.set.call_args.kwargs["timeout"] == ttl


def test_probe_does_not_connect_in_dev_mode(monkeypatch) -> None:
    connect = MagicMock()
    monkeypatch.setattr(duckgres_availability, "connect_to_duckgres", connect)
    monkeypatch.setattr(duckgres_availability, "is_dev_mode", lambda: True)

    assert probe_duckgres_organization(_server()) is DuckgresOrganizationStatus.UNKNOWN

    connect.assert_not_called()
