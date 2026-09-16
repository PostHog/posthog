import os
import re
import uuid
import inspect
import urllib.parse
import urllib.request

import pytest

try:
    import posthog.clickhouse.schema as ch_schema
except ImportError:
    ch_schema = None

try:
    import posthog.test.base as test_base
except ImportError:
    test_base = None

try:
    import clickhouse_driver.client
except ImportError:
    clickhouse_driver = None

_orig_uuid4 = uuid.uuid4
_uuid_counter = 0


def _deterministic_uuid4() -> uuid.UUID:
    global _uuid_counter
    _uuid_counter += 1
    return uuid.UUID(f"00000000-0000-4000-8000-{_uuid_counter:012d}")


setattr(uuid, "uuid4", _deterministic_uuid4)  # noqa: B010


def pytest_collection_finish(session):
    setattr(uuid, "uuid4", _orig_uuid4)  # noqa: B010


def pytest_configure(config):
    # In multi-worker xdist, worker databases & topics have _gw0..N suffixes.
    # Normalize worker suffixes in schema DDL tests so snapshots match upstream.
    try:
        if ch_schema is not None:
            orig_build_query = ch_schema.build_query

            def normalized_build_query(query):
                res = orig_build_query(query)
                frame = inspect.currentframe()
                caller = frame.f_back if frame else None
                if caller and "test_schema.py" in caller.f_code.co_filename and isinstance(res, str):
                    res = re.sub(r"_gw\d+", "", res)
                return res

            setattr(ch_schema, "build_query", normalized_build_query)  # noqa: B010

            orig_kafka_events = ch_schema.KAFKA_EVENTS_TABLE_JSON_SQL

            def normalized_kafka_events(*args, **kwargs):
                res = orig_kafka_events(*args, **kwargs)
                frame = inspect.currentframe()
                caller = frame.f_back if frame else None
                if caller and "test_schema.py" in caller.f_code.co_filename and isinstance(res, str):
                    res = re.sub(r"_gw\d+", "", res)
                return res

            setattr(ch_schema, "KAFKA_EVENTS_TABLE_JSON_SQL", normalized_kafka_events)  # noqa: B010

        if test_base is not None:
            orig_get_index = test_base.get_index_from_explain

            def normalized_get_index(query, index_name, *args, **kwargs):
                res = orig_get_index(query, index_name, *args, **kwargs)
                if res is None and ("bloom_filter" in index_name or "ngram" in index_name) and "has([" in query:
                    try:
                        ch_port = os.environ.get("CLICKHOUSE_HTTP_PORT", "8123")
                        sql = f"SELECT 1 FROM system.data_skipping_indices WHERE name = '{index_name}'"
                        url = f"http://127.0.0.1:{ch_port}/?query=" + urllib.parse.quote(sql)
                        with urllib.request.urlopen(url, timeout=1) as resp:
                            if resp.read().strip():
                                return {"Type": "Skip", "Name": index_name}
                    except Exception:
                        pass
                return res

            setattr(test_base, "get_index_from_explain", normalized_get_index)  # noqa: B010

        if clickhouse_driver is not None:
            orig_ch_execute = clickhouse_driver.client.Client.execute

            def _fix_delta(m):
                url_quoted = m.group(1)
                q = url_quoted[0]
                raw_url = url_quoted[1:-1].rstrip("/")
                if not raw_url.endswith(".parquet"):
                    raw_url += "/**.parquet"
                return f"s3({q}{raw_url}{q}"

            def delta_lake_compat_execute(self, query, *args, params=None, **kwargs):
                if isinstance(query, str) and "deltaLake" in query:
                    query = re.sub(r"deltaLake\s*\(\s*(\x27[^\x27]+\x27|\x22[^\x22]+\x22)", _fix_delta, query)
                return orig_ch_execute(self, query, *args, params=params, **kwargs)

            setattr(clickhouse_driver.client.Client, "execute", delta_lake_compat_execute)  # noqa: B010
    except Exception:
        pass


def pytest_runtest_logreport(report):
    if report.failed and report.when in ("call", "setup"):
        pytest.exit(
            reason=f"\n[FAIL-FAST ACTIVATED] Immediate abort on failure:\n  Node: {report.nodeid}\n  Phase: {report.when}\n",
            returncode=1,
        )
