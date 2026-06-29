"""Per-test resource-utilization profiler.

A passive passenger on a normal test run: for every test it records what
expensive resources the test *provisioned* versus what it actually *used*, so we
can find tests paying setup cost for nothing. Self-sufficient — it records its
own per-test wall time and status, so no junit or coverage correlation is needed.

Signals captured per test:
  - db_enabled        : Postgres set up (django_db marker or a Django TestCase base)
  - pg_{setup,call,teardown} : Postgres queries per phase
  - pg_alias          : Postgres queries per connection alias (multi-DB over-declaration)
  - declared_dbs      : the TestCase.databases declaration (what got transaction-wrapped)
  - ch_provisioned    : test uses a ClickHouse test mixin
  - ch_call           : ClickHouse queries during the test body
  - on_commit         : transaction.on_commit registrations (TransactionTestCase necessity)
  - for_update        : issued SELECT ... FOR UPDATE (TransactionTestCase necessity)
  - duration_s        : call-phase wall time (perf_counter)
  - base, status

Derived waste buckets (computed by tools/test_resource_report.py):
  - no-DB        : db_enabled & pg_total==0 & ch_call==0      -> SimpleTestCase
  - CH-unused    : ch_provisioned & ch_call==0               -> drop the CH mixin
  - txn-downgrade: TransactionTestCase base & no on_commit & no FOR UPDATE & single conn -> TestCase
  - multi-DB-trim: declared_dbs has aliases never queried     -> trim `databases`

Load with:  pytest -p tools.pytest_resource_profiler ...
Output:     JSONL at $RESOURCE_PROFILE_OUT (one row per test).

Only Postgres/ClickHouse are counted — the two datastores whose per-test setup
actually costs something here.
"""

from __future__ import annotations

import os
import json
import time
import inspect
import contextlib
from pathlib import Path

import pytest

_DEFAULT_OUT = "logs/resource_profile.jsonl"

# Test base classes worth grouping by, cheapest to most expensive.
_KNOWN_BASES = {
    "SimpleTestCase",
    "TestCase",
    "APIBaseTest",
    "BaseTest",
    "QueryMatchingTest",
    "TransactionTestCase",
    "APITransactionBaseTest",
}

_records: dict[str, dict] = {}


def _db_enabled(item: pytest.Item, cls) -> bool:
    if item.get_closest_marker("django_db") is not None:
        return True
    if cls is None:
        return False
    try:
        from django.test import TransactionTestCase  # noqa: PLC0415 — Django configured at runtime only

        return issubclass(cls, TransactionTestCase)
    except Exception:
        return False


def _is_txn(item: pytest.Item, cls) -> bool:
    """The *slow* TransactionTestCase (truncates tables), not Django's fast TestCase subclass of it."""
    marker = item.get_closest_marker("django_db")
    if marker is not None and marker.kwargs.get("transaction"):
        return True
    if cls is None:
        return False
    try:
        from django.test import TestCase, TransactionTestCase  # noqa: PLC0415 — Django configured at runtime only

        return issubclass(cls, TransactionTestCase) and not issubclass(cls, TestCase)
    except Exception:
        return False


def _testcase_base(cls) -> str:
    if cls is None:
        return "function"
    for ancestor in cls.__mro__[1:]:
        if ancestor.__name__ in _KNOWN_BASES:
            return ancestor.__name__
    return cls.__mro__[1].__name__ if len(cls.__mro__) > 1 else cls.__name__


def _declared_dbs(cls):
    """The `databases` the TestCase wraps in transactions; None for plain functions."""
    dbs = getattr(cls, "databases", None) if cls is not None else None
    if dbs is None:
        return None
    if dbs == "__all__":
        return "__all__"
    try:
        return sorted(str(d) for d in dbs)
    except TypeError:
        return str(dbs)


def _ch_provisioned(cls) -> bool:
    if cls is None:
        return False
    return any("Clickhouse" in a.__name__ or "ClickHouse" in a.__name__ for a in cls.__mro__)


def _is_async(item: pytest.Item) -> bool:
    """Async tests often need transaction=True for the async/sync ORM boundary — never a txn-downgrade."""
    func = getattr(item, "function", None) or getattr(item, "obj", None)
    return bool(func) and inspect.iscoroutinefunction(func)


def _new_record(item: pytest.Item) -> dict:
    cls = getattr(item, "cls", None)
    return {
        "nodeid": item.nodeid,
        "file": str(item.path) if getattr(item, "path", None) else "",
        "base": _testcase_base(cls),
        "is_txn": _is_txn(item, cls),
        "is_async": _is_async(item),
        "db_enabled": _db_enabled(item, cls),
        "declared_dbs": _declared_dbs(cls),
        "ch_provisioned": _ch_provisioned(cls),
        "pg_setup": 0,
        "pg_call": 0,
        "pg_teardown": 0,
        "pg_alias": {},
        "ch_call": 0,
        "on_commit": 0,
        "for_update": False,
        "duration_s": 0.0,
        "status": "unknown",
    }


def _record_for(item: pytest.Item) -> dict:
    rec = _records.get(item.nodeid)
    if rec is None:
        rec = _new_record(item)
        _records[item.nodeid] = rec
    return rec


@contextlib.contextmanager
def _wrap_pg(rec: dict, phase: str):
    """Count Postgres queries per connection alias and watch for SELECT ... FOR UPDATE."""
    counts: dict[str, int] = {}
    try:
        from django.db import connections  # noqa: PLC0415 — Django configured at runtime only

        stack: contextlib.AbstractContextManager = contextlib.ExitStack()

        def make(alias: str):
            def wrapper(execute, sql, params, many, context):
                counts[alias] = counts.get(alias, 0) + 1
                if not rec["for_update"] and isinstance(sql, str) and "FOR UPDATE" in sql.upper():
                    rec["for_update"] = True
                return execute(sql, params, many, context)

            return wrapper

        for conn in connections.all():
            stack.enter_context(conn.execute_wrapper(make(conn.alias)))
    except Exception:
        stack = contextlib.nullcontext()
    try:
        with stack:
            yield
    finally:
        rec[f"pg_{phase}"] += sum(counts.values())
        for alias, n in counts.items():
            rec["pg_alias"][alias] = rec["pg_alias"].get(alias, 0) + n


@contextlib.contextmanager
def _wrap_ch(rec: dict):
    """Count ClickHouse queries during the test body (only for CH-provisioned tests)."""
    if not rec["ch_provisioned"]:
        yield
        return
    counter = {"n": 0}
    try:
        from posthog.test.base import patch_clickhouse_client_execute  # noqa: PLC0415 — heavy test-only dep

        def chw(orig_execute, query, *args, **kwargs):
            counter["n"] += 1
            return orig_execute(query, *args, **kwargs)

        cm: contextlib.AbstractContextManager = patch_clickhouse_client_execute(chw)
    except Exception:
        cm = contextlib.nullcontext()
    try:
        with cm:
            yield
    finally:
        rec["ch_call"] += counter["n"]


@contextlib.contextmanager
def _wrap_on_commit(rec: dict):
    """Count transaction.on_commit registrations (attribute-access form)."""
    try:
        from unittest import mock  # noqa: PLC0415 — test-only

        from django.db import transaction  # noqa: PLC0415 — Django configured at runtime only

        original = transaction.on_commit
    except Exception:
        yield
        return

    def counting(func, using=None, robust=False):
        rec["on_commit"] += 1
        return original(func, using=using, robust=robust)

    with mock.patch("django.db.transaction.on_commit", side_effect=counting):
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    with _wrap_pg(_record_for(item), "setup"):
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    rec = _record_for(item)
    start = time.perf_counter()
    with _wrap_pg(rec, "call"), _wrap_ch(rec), _wrap_on_commit(rec):
        yield
    rec["duration_s"] = time.perf_counter() - start


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    with _wrap_pg(_record_for(item), "teardown"):
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item):
    out = yield
    report = out.get_result()
    rec = _record_for(item)
    if report.when == "call":
        rec["status"] = report.outcome
    elif report.when == "setup" and report.outcome in {"skipped", "failed"} and rec["status"] == "unknown":
        rec["status"] = report.outcome


def pytest_sessionfinish():
    out = Path(os.environ.get("RESOURCE_PROFILE_OUT", _DEFAULT_OUT))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as fh:
        for rec in _records.values():
            rec["pg_total"] = rec["pg_setup"] + rec["pg_call"] + rec["pg_teardown"]
            fh.write(json.dumps(rec) + "\n")
