from __future__ import annotations

from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock

from hogli_commands import isolated_tests
from psycopg import sql


@pytest.mark.parametrize("worker", [None, "gw0"])
def test_cleanup_only_drops_the_current_invocations_databases(
    monkeypatch: pytest.MonkeyPatch, worker: str | None
) -> None:
    run_id = "0123456789abcdef"
    prefix = f"test_posthog_{run_id}" + ("_gw0" if worker else "")
    databases = {prefix, prefix + "_persons", "test_posthog", "test_posthog_fedcba9876543210"}
    if worker:
        databases.add(f"test_posthog_{run_id}_gw1")
        databases.add(f"test_posthog_{run_id}_stamphog_gw0")
        databases.add(f"test_posthog_{run_id}_stamphog_gw1")
    connection = MagicMock()
    clickhouse = MagicMock()
    clickhouse_name = f"posthog_test{'_gw0' if worker else ''}_{run_id}"
    clickhouse_names = {"posthog_test", clickhouse_name, "posthog_test_gw1_fedcba9876543210"}

    def raw(query: str) -> str:
        if query == "SHOW DATABASES":
            return "\n".join(clickhouse_names)
        clickhouse_names.discard(query.split()[4])
        return ""

    clickhouse.raw.side_effect = raw
    connection.__enter__.return_value = connection
    django_connections = MagicMock()
    open_connection = True

    def close_connections() -> None:
        nonlocal open_connection
        open_connection = False

    django_connections.close_all.side_effect = close_connections

    def execute(query: str | sql.Composed) -> SimpleNamespace | None:
        if isinstance(query, str):
            return SimpleNamespace(fetchall=lambda: [(name,) for name in databases])
        if open_connection:
            raise RuntimeError("The current process still has an open database connection")
        name = query.as_string().split('"')[1]
        databases.remove(name)

    connection.execute.side_effect = execute
    monkeypatch.setattr(isolated_tests, "settings", SimpleNamespace(TEST_RUN_ID=run_id, DATABASES={"default": {}}))
    monkeypatch.setattr(isolated_tests, "_connect", lambda: connection)
    monkeypatch.setattr(isolated_tests, "_clickhouse", lambda: clickhouse)
    monkeypatch.setattr(isolated_tests, "connections", django_connections, raising=False)
    if worker:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
    else:
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    session = MagicMock()
    session.config.stash = pytest.Stash()
    with pytest.raises(pytest.UsageError, match="namespace already exists"):
        isolated_tests.pytest_sessionstart(session)
    isolated_tests.pytest_sessionfinish(session)
    assert prefix in databases
    owned = {
        name
        for name in databases
        if name == prefix or name.startswith(prefix + "_") or (worker and name.endswith("_gw0"))
    }
    databases.difference_update(owned)
    clickhouse_names.remove(clickhouse_name)
    isolated_tests.pytest_sessionstart(session)
    databases.update(owned)
    clickhouse_names.add(clickhouse_name)
    isolated_tests.pytest_sessionfinish(session)
    assert databases == {"test_posthog", "test_posthog_fedcba9876543210"} | (
        {f"test_posthog_{run_id}_gw1", f"test_posthog_{run_id}_stamphog_gw1"} if worker else set()
    )
    assert clickhouse_names == {"posthog_test", "posthog_test_gw1_fedcba9876543210"}


def test_cleanup_reports_busy_databases_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = "test_posthog_0123456789abcdef"
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = [(prefix,), (prefix + "_persons",)]
    dropped: list[str] = []

    def execute(query: str | sql.Composed) -> MagicMock | None:
        if isinstance(query, str):
            return MagicMock(fetchall=lambda: [(prefix,), (prefix + "_persons",)])
        name = query.as_string().split('"')[1]
        if name == prefix:
            raise RuntimeError("database is busy")
        dropped.append(name)
        return None

    connection.execute.side_effect = execute
    clickhouse = MagicMock()
    clickhouse.raw.side_effect = ["posthog_test_0123456789abcdef", ""]
    monkeypatch.setattr(isolated_tests, "_connect", lambda: connection)
    monkeypatch.setattr(isolated_tests, "_clickhouse", lambda: clickhouse)
    monkeypatch.setattr(isolated_tests, "settings", SimpleNamespace(TEST_RUN_ID="0123456789abcdef"))
    monkeypatch.setattr(isolated_tests, "connections", MagicMock())
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    session = MagicMock()
    session.config.stash = pytest.Stash()
    session.config.stash[isolated_tests._owned_namespace] = prefix
    session.exitstatus = pytest.ExitCode.OK
    isolated_tests.pytest_sessionfinish(session)
    assert dropped == [prefix + "_persons"]
    clickhouse.raw.assert_called_with("DROP DATABASE IF EXISTS posthog_test_0123456789abcdef SYNC")
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert prefix in session.config.pluginmanager.get_plugin.return_value.write_line.call_args.args[0]
