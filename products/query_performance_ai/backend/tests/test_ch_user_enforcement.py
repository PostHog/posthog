"""Integration tests for the ``autoresearch`` ClickHouse user enforcement.

Hits the live CH server provisioned by ``docker/clickhouse/users-dev.xml``
and ``autoresearch-row-policies.sql``. **Fails** (not skips) when CH is
unreachable — a silent skip turns the SQL-safety story into wishful
thinking.
"""

from __future__ import annotations

import pytest

from django.conf import settings

from clickhouse_driver import (
    Client as SyncClient,
    errors as ch_errors,
)

CH_ACCESS_DENIED = 497
CH_READONLY = 164
# `file()` with an absolute path outside user_files_path trips path-check (291)
# before authz fires. Either refusal is fine — data never reaches the caller.
CH_PATH_OUTSIDE_USER_FILES = 291


def _assert_test_cluster_configured() -> None:
    if not settings.CLICKHOUSE_TEST_CLUSTER_HOST or not settings.CLICKHOUSE_TEST_CLUSTER_USER:
        pytest.fail(
            "CLICKHOUSE_TEST_CLUSTER_HOST / _USER not configured — run `bin/start` locally "
            "(or set the env vars in CI) before running this test."
        )


@pytest.fixture(scope="module")
def autoresearch_client() -> SyncClient:
    _assert_test_cluster_configured()
    client = SyncClient(
        host=settings.CLICKHOUSE_TEST_CLUSTER_HOST,
        database=settings.CLICKHOUSE_TEST_CLUSTER_DATABASE or "default",
        user=settings.CLICKHOUSE_TEST_CLUSTER_USER,
        password=settings.CLICKHOUSE_TEST_CLUSTER_PASSWORD,
        secure=settings.CLICKHOUSE_TEST_CLUSTER_SECURE,
        ca_certs=settings.CLICKHOUSE_TEST_CLUSTER_CA,
        verify=settings.CLICKHOUSE_TEST_CLUSTER_VERIFY,
        connect_timeout=2,
    )
    try:
        current = client.execute("SELECT currentUser()")
    except Exception as e:
        pytest.fail(f"autoresearch CH user unreachable ({e!r}) — ensure CH is up and `autoresearch` user exists")
    expected = settings.CLICKHOUSE_TEST_CLUSTER_USER
    assert current == [(expected,)], f"unexpected currentUser(): {current!r} (expected {expected!r})"
    return client


@pytest.fixture(scope="module")
def default_client() -> SyncClient:
    """Regular CH user — needed as a *different* user to exercise the
    row-policy cross-user check."""
    client = SyncClient(
        host=settings.CLICKHOUSE_HOST,
        database="default",
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        secure=settings.CLICKHOUSE_SECURE,
        ca_certs=settings.CLICKHOUSE_CA,
        verify=settings.CLICKHOUSE_VERIFY,
        connect_timeout=2,
    )
    try:
        client.execute("SELECT 1")
    except Exception as e:
        pytest.fail(f"regular CH user unreachable ({e!r}) — ensure CH is up")
    if settings.CLICKHOUSE_USER == settings.CLICKHOUSE_TEST_CLUSTER_USER:
        pytest.fail("regular CH user matches autoresearch user; row-policy cross-user check can't be verified")
    return client


# --- table-function blocks ---------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM url('http://example.com/', CSV, 'x String') LIMIT 1",
        "SELECT * FROM s3('https://example.com/x.csv', 'CSV', 'x String') LIMIT 1",
        # Relative path → grant check; absolute paths trip the path check first.
        "SELECT * FROM file('foo.csv', 'CSV', 'x String') LIMIT 1",
        "SELECT * FROM remote('example.com:9000', default.x) LIMIT 1",
        "SELECT * FROM mysql('host:3306', 'db', 't', 'u', 'p') LIMIT 1",
        "SELECT * FROM postgresql('host', 'db', 't', 'u', 'p') LIMIT 1",
        "SELECT * FROM executable('whoami', CSV, 'x String') LIMIT 1",
    ],
)
def test_dangerous_table_functions_are_rejected(autoresearch_client: SyncClient, sql: str) -> None:
    with pytest.raises(ch_errors.ServerException) as exc_info:
        autoresearch_client.execute(sql)
    assert exc_info.value.code in (CH_ACCESS_DENIED, CH_PATH_OUTSIDE_USER_FILES), (
        f"unexpected code for {sql!r}: {exc_info.value!r}"
    )


# --- readonly enforcement ----------------------------------------------------


def test_insert_rejected(autoresearch_client: SyncClient) -> None:
    # system.query_log doesn't depend on migrations having run.
    with pytest.raises(ch_errors.ServerException) as exc_info:
        autoresearch_client.execute("INSERT INTO system.query_log SELECT * FROM system.query_log LIMIT 0")
    assert exc_info.value.code in (CH_ACCESS_DENIED, CH_READONLY), (
        f"INSERT should have been blocked, got code {exc_info.value.code}"
    )


def test_client_cannot_override_readonly(autoresearch_client: SyncClient) -> None:
    # The profile pins readonly via <constraints>; client overrides are refused.
    with pytest.raises(ch_errors.ServerException) as exc_info:
        autoresearch_client.execute("SELECT 1 SETTINGS readonly=0")
    assert exc_info.value.code == CH_READONLY


# --- positive paths ----------------------------------------------------------


def test_whitelisted_select_works(autoresearch_client: SyncClient) -> None:
    result = autoresearch_client.execute("SELECT count() FROM system.query_log")
    assert isinstance(result, list) and len(result) == 1


def test_explain_select_works(autoresearch_client: SyncClient) -> None:
    # EXPLAIN inherits SELECT privileges. Regression guard against CH changing this.
    result = autoresearch_client.execute("EXPLAIN SELECT count() FROM system.query_log")
    assert isinstance(result, list) and len(result) > 0


def test_query_log_readable(autoresearch_client: SyncClient) -> None:
    # Logs flush async; we just need the query to not be rejected.
    autoresearch_client.execute("SELECT count() FROM system.query_log")


def test_profiling_tables_readable(autoresearch_client: SyncClient) -> None:
    # SKILL.md tells the agent to inspect these for ProfileEvents / per-thread
    # / server-log / sampled-stack profiling. Confirm grant + row policy don't
    # together deny the SELECT. trace_log / text_log are only present when CH
    # is built with profiler sampling / text_log config enabled — tolerate
    # absence so the test runs against stock CH images.
    checked = 0
    for table in ("system.query_thread_log", "system.text_log", "system.trace_log"):
        try:
            autoresearch_client.execute(f"SELECT count() FROM {table}")
            checked += 1
        except ch_errors.ServerException as e:
            if e.code == 60:
                continue
            raise
    if checked == 0:
        pytest.skip("none of the profiling tables exist on this CH build")


# --- row policy on system profiling tables ----------------------------------


def test_query_log_row_policy_hides_other_users(autoresearch_client: SyncClient, default_client: SyncClient) -> None:
    autoresearch_client.execute("SELECT 'autoresearch-row-policy-probe' AS marker")
    default_client.execute("SELECT 'default-row-policy-probe' AS marker")
    default_client.execute("SYSTEM FLUSH LOGS")

    as_autoresearch = autoresearch_client.execute("SELECT DISTINCT initial_user FROM system.query_log")
    as_default = default_client.execute("SELECT DISTINCT initial_user FROM system.query_log")

    autoresearch_users = {row[0] for row in as_autoresearch}
    default_users = {row[0] for row in as_default}

    expected_autoresearch_user = settings.CLICKHOUSE_TEST_CLUSTER_USER
    assert autoresearch_users == {expected_autoresearch_user}, (
        f"row policy on system.query_log leaked other users: {autoresearch_users}"
    )
    assert settings.CLICKHOUSE_USER in default_users, (
        f"regular CH user should see its own rows at minimum: {default_users}"
    )


def test_query_thread_log_row_policy_hides_other_users(
    autoresearch_client: SyncClient, default_client: SyncClient
) -> None:
    autoresearch_client.execute("SELECT 'autoresearch-thread-probe' AS marker")
    default_client.execute("SELECT 'default-thread-probe' AS marker")
    default_client.execute("SYSTEM FLUSH LOGS")

    as_autoresearch = autoresearch_client.execute("SELECT DISTINCT initial_user FROM system.query_thread_log")

    autoresearch_users = {row[0] for row in as_autoresearch}
    expected_autoresearch_user = settings.CLICKHOUSE_TEST_CLUSTER_USER
    # query_thread_log may be empty when log_query_threads=0; tolerate that.
    if autoresearch_users:
        assert autoresearch_users == {expected_autoresearch_user}, (
            f"row policy on system.query_thread_log leaked other users: {autoresearch_users}"
        )


def test_text_log_row_policy_hides_other_users_queries(
    autoresearch_client: SyncClient, default_client: SyncClient
) -> None:
    # text_log has no `user` column; the policy filters by query_id ∈ user's
    # query_log. Verify the autoresearch user can't see text_log rows whose
    # query_id was minted by the default user.
    autoresearch_marker = "autoresearch-text-log-probe-{}".format(__import__("uuid").uuid4().hex[:8])
    default_marker = "default-text-log-probe-{}".format(__import__("uuid").uuid4().hex[:8])
    autoresearch_client.execute(f"SELECT '{autoresearch_marker}' AS marker SETTINGS log_queries=1")
    default_client.execute(f"SELECT '{default_marker}' AS marker SETTINGS log_queries=1")
    default_client.execute("SYSTEM FLUSH LOGS")

    as_default = default_client.execute(f"SELECT count() FROM system.text_log WHERE message LIKE '%{default_marker}%'")
    if as_default[0][0] == 0:
        # text_log may not capture this kind of marker on this CH build; skip.
        pytest.skip("text_log does not capture select-marker text on this CH build")

    as_autoresearch = autoresearch_client.execute(
        f"SELECT count() FROM system.text_log WHERE message LIKE '%{default_marker}%'"
    )
    assert as_autoresearch[0][0] == 0, (
        f"autoresearch user saw text_log entries from a different user's query (marker={default_marker!r})"
    )
