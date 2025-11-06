import os
import sys
from contextlib import contextmanager
from functools import wraps
from os.path import dirname

from django.utils.timezone import now

os.environ["POSTHOG_DB_NAME"] = "posthog_test"
os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
sys.path.append(dirname(dirname(dirname(__file__))))

import django  # noqa: E402

django.setup()

from posthog import client  # noqa: E402
from posthog.clickhouse.query_tagging import reset_query_tags, tag_queries  # noqa: E402
from posthog.models.utils import UUIDT  # noqa: E402

from products.enterprise.backend.clickhouse.materialized_columns.columns import (  # noqa: E402
    get_enabled_materialized_columns,  # noqa: E402
)  # noqa: E402

get_column = lambda rows, index: [row[index] for row in rows]


def run_query(fn, *args):
    uuid = str(UUIDT())
    tag_queries(kind="benchmark", id=f"{uuid}::${fn.__name__}")
    try:
        fn(*args)
        return get_clickhouse_query_stats(uuid)
    finally:
        reset_query_tags()


def get_clickhouse_query_stats(uuid):
    client.sync_execute("SYSTEM FLUSH LOGS")
    rows = client.sync_execute(
        f"""
        SELECT
            query_duration_ms,
            read_rows,
            read_bytes,
            memory_usage
        FROM system.query_log
        WHERE
            query NOT LIKE '%%query_log%%'
            AND query LIKE %(matcher)s
            AND type = 'QueryFinish'
        """,
        {"matcher": f"%benchmark:{uuid}%"},
    )

    return {
        "query_count": len(rows),
        "ch_query_time": int(sum(get_column(rows, 0))),
        "read_rows": sum(get_column(rows, 1)),
        "read_bytes": sum(get_column(rows, 2)),
        "memory_usage": sum(get_column(rows, 3)),
    }


def benchmark_clickhouse(fn):
    @wraps(fn)
    def inner(*args):
        samples = [run_query(fn, *args)["ch_query_time"] for _ in range(4)]
        return {"samples": samples, "number": len(samples)}

    return inner


@contextmanager
def no_materialized_columns():
    "Allows running a function without any materialized columns being used in query"
    get_enabled_materialized_columns._cache = {
        ("events",): (now(), {}),
        ("person",): (now(), {}),
    }
    yield
    get_enabled_materialized_columns._cache = {}
