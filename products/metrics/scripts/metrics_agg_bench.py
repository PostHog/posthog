#!/usr/bin/env python3
"""Benchmark the `metrics2_agg` array layout against `metrics2` with snuffle's queries.

The script creates `metrics2`, `metric_series2`, and `metrics2_agg` with the
MVs that fill them from `metrics2_input` in a scratch database. It generates
synthetic labelled points server-side and inserts them in small chunks so
`metrics2_agg` gets partial rows. It then starts a snuffle binary against the
scratch database, sends PromQL range queries, and captures the ClickHouse SQL
that snuffle runs. Snuffle does the rollups inside ClickHouse: it builds one
`(ts, value)` array per series from `metrics2`, sorts it, and evaluates the
PromQL function over the array. The array variant of each captured query
replaces only that first stage with a read of the per-hour arrays in
`metrics2_agg`; every later stage is identical. The matrix runs twice, with
merges stopped and after `OPTIMIZE TABLE ... FINAL`, checks that both variants
return the same rows, and prints a markdown report.

Usage, from the repo root with the dev stack running and snuffle built
(`go build -o /tmp/snuffle ./cmd/snuffle` in a PostHog/snuffle checkout):

    CLICKHOUSE_LOGS_DATABASE=metrics_bench PYTHONPATH=. \\
        python products/metrics/scripts/metrics_agg_bench.py --snuffle-bin /tmp/snuffle

`CLICKHOUSE_LOGS_DATABASE` selects the scratch database; the script drops and
recreates it unless `--keep` is set. The engines are rewritten to their
non-replicated forms, so the objects never touch the Keeper paths of the real
tables.
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import argparse
import datetime as dt
import statistics
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("DEBUG", "1")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from clickhouse_driver import Client  # noqa: E402

from posthog.clickhouse.metrics import (  # noqa: E402
    METRIC_SERIES2_TABLE_SQL,
    METRICS2_AGG_TABLE_SQL,
    METRICS2_INPUT_TABLE_SQL,
    METRICS2_INPUT_TO_METRIC_SERIES_MV,
    METRICS2_INPUT_TO_METRICS_AGG_MV,
    METRICS2_INPUT_TO_METRICS_MV,
    METRICS2_TABLE_SQL,
)
from posthog.clickhouse.metrics.metrics_agg import ARRAY_CODECS, POINT_ARRAY_COLUMNS  # noqa: E402

BASE_TIME = dt.datetime(2026, 9, 1, 0, 0, tzinfo=dt.UTC)
TABLES = ("metrics2", "metrics2_agg")
SERIES_TABLE = "metric_series2"

# (name, PromQL, step seconds, range hours). `metric_0` is a gauge, `metric_1` a
# cumulative counter; both have 50 series per team with a `host` label.
PROMQL_CASES: tuple[tuple[str, str, int, int], ...] = (
    ("gauge_avg_5m_6h", "avg(metric_0)", 300, 6),
    ("gauge_sum_by_host_5m_6h", "sum(metric_0) by (host)", 300, 6),
    ("gauge_max_1h_24h", "max(metric_0)", 3600, 24),
    ("gauge_filtered_host_5m_6h", 'avg(metric_0{host=~"host-1.*"})', 300, 6),
    ("counter_sum_rate_5m_1m_6h", "sum(rate(metric_1[5m]))", 60, 6),
    ("counter_rate_by_host_5m_24h", "sum(rate(metric_1[5m])) by (host)", 300, 24),
    ("counter_increase_1h_24h", "sum(increase(metric_1[1h]))", 3600, 24),
)

_SAMPLES_STAGE = re.compile(
    r"SELECT series_id, arraySort\(x -> x\.1, groupArray\(\(ts, v\)\)\) AS pts, (?P<middle>.*?) "
    r"FROM \(SELECT series_fingerprint AS series_id, toUnixTimestamp64Milli\(timestamp\) AS ts, value AS v "
    r"FROM `(?P<db>\w+)`\.`metrics2` WHERE (?P<where>.*?)\) GROUP BY series_id\)",
    re.DOTALL,
)
_TIME_PREDICATE = re.compile(r"^timestamp (?P<op>>=|<=) fromUnixTimestamp64Milli\((?P<ms>\d+), 'UTC'\)$")
_VALUE_PREDICATE = re.compile(r"^reinterpretAsUInt64\(value\) != \d+$")


def _unreplicated(sql: str) -> str:
    return re.sub(r"Replicated(\w*MergeTree)\('[^']*',\s*'[^']*'(?:,\s*)?", r"\1(", sql)


def _ts(value: dt.datetime) -> str:
    return f"toDateTime64('{value.strftime('%Y-%m-%d %H:%M:%S')}', 6, 'UTC')"


def to_agg_sql(sql: str) -> str:
    """Rewrite the samples stage of a snuffle query to read `metrics2_agg`.

    Key predicates stay in WHERE. Predicates on `timestamp` and `value` move
    into an `arrayFilter` over the zipped points, because one hour row holds
    points outside the requested window. Unknown predicates raise, so a new
    snuffle filter cannot silently change what the two variants compare.

    `pts` is built in its own subquery. In snuffle's query `pts` is an aggregate
    result, which ClickHouse computes once. An `arraySort(arrayFilter(...))`
    alias in the same SELECT is re-evaluated for every column that references
    it, which made the array variant 30 to 50 % slower than the row table.
    """
    match = _SAMPLES_STAGE.search(sql)
    if match is None:
        raise ValueError("snuffle query has no recognised samples stage")
    keep: list[str] = []
    point: list[str] = []
    for predicate in match.group("where").split(" AND "):
        if time_match := _TIME_PREDICATE.match(predicate):
            point.append(f"p.1 {time_match.group('op')} {time_match.group('ms')}")
        elif _VALUE_PREDICATE.match(predicate):
            point.append(predicate.replace("reinterpretAsUInt64(value)", "reinterpretAsUInt64(p.2)"))
        elif re.match(r"^(team_id|time_bucket|metric_name|service_name|series_fingerprint) ", predicate):
            keep.append(predicate)
        else:
            raise ValueError(f"unhandled snuffle predicate: {predicate}")
    points = "groupArrayArray(arrayZip(arrayMap(t -> toUnixTimestamp64Milli(t), timestamp_arr), value_arr))"
    if point:
        points = f"arrayFilter(p -> {' AND '.join(point)}, {points})"
    inner = (
        f"SELECT series_fingerprint AS series_id, arraySort(x -> x.1, {points}) AS pts "
        f"FROM `{match.group('db')}`.`metrics2_agg` WHERE {' AND '.join(keep)} GROUP BY series_id"
    )
    replacement = f"SELECT series_id, pts, {match.group('middle')} FROM ({inner}))"
    return sql[: match.start()] + replacement + sql[match.end() :]


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    user: str
    password: str
    db: str
    teams: int
    metrics: int
    series: int
    days: int
    scrape_seconds: int
    chunk_minutes: int
    runs: int
    threads: int
    skip_generate: bool
    keep: bool
    snuffle_bin: str
    snuffle_port: int
    agg_index_granularity: int
    json_path: str | None
    out_path: str | None

    @property
    def n_series(self) -> int:
        return self.teams * self.metrics * self.series

    @property
    def date_to(self) -> dt.datetime:
        return BASE_TIME + dt.timedelta(days=self.days)


@dataclass(frozen=True)
class Measurement:
    query: str
    variant: str
    state: str
    median_ms: float
    min_ms: float
    read_rows: int
    read_bytes: int
    memory_bytes: int
    selected_marks: int
    selected_parts: int
    granules: str
    rows_returned: int
    equal: str


@dataclass(frozen=False)
class Report:
    config: Config
    codec_note: str = ""
    storage: list[dict[str, Any]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)
    queries: dict[str, dict[str, str]] = field(default_factory=dict)
    checks: list[str] = field(default_factory=list)


class Snuffle:
    """Run a snuffle binary against the scratch database and capture its SQL."""

    def __init__(self, cfg: Config, client: Client) -> None:
        self.cfg = cfg
        self.client = client
        self.process: subprocess.Popen[bytes] | None = None
        self.url = f"http://localhost:{cfg.snuffle_port}"

    def __enter__(self) -> Snuffle:
        env = {
            **os.environ,
            "CH_ADDR": f"{self.cfg.host}:{self.cfg.port}",
            "CH_USER": self.cfg.user,
            "CH_PASSWORD": self.cfg.password,
            "CH_DATABASE": self.cfg.db,
            "CH_SCHEMA_LAYOUT": "posthog",
            "CH_SERIES_TABLE": SERIES_TABLE,
            "CH_RANGE_QUERY_MAX_THREADS": str(self.cfg.threads),
            "SIDECAR_PORT": str(self.cfg.snuffle_port),
            "SNUFFLE_SELF_SCRAPE_ENABLED": "false",
        }
        self.process = subprocess.Popen(
            [self.cfg.snuffle_bin], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"{self.url}/-/ready", timeout=1) as response:
                    if response.status == 200:
                        return self
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("snuffle did not become ready")

    def __exit__(self, *exc: object) -> None:
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=10)

    def capture(self, promql: str, start: dt.datetime, end: dt.datetime, step: int) -> str:
        """Return the ClickHouse SQL snuffle ran for one range query."""
        params = urllib.parse.urlencode(
            {"query": promql, "start": int(start.timestamp()), "end": int(end.timestamp()), "step": step}
        )
        since = self.client.execute("SELECT now64(3)")[0][0]
        request = urllib.request.Request(f"{self.url}/api/v1/query_range?{params}", headers={"X-Team-ID": "1"})
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
        if payload.get("status") != "success" or not payload["data"]["result"]:
            raise RuntimeError(f"snuffle returned no data for {promql!r}: {str(payload)[:300]}")
        self.client.execute("SYSTEM FLUSH LOGS")
        rows = self.client.execute(
            """
            SELECT query FROM system.query_log
            WHERE type = 'QueryFinish' AND query_kind = 'Select' AND current_database = %(db)s
              AND event_time_microseconds >= %(since)s AND query LIKE '%%groupArray((ts, v))%%'
            ORDER BY event_time_microseconds DESC LIMIT 1
            """,
            {"db": self.cfg.db, "since": since},
        )
        if not rows:
            raise RuntimeError(f"snuffle did not push {promql!r} down to ClickHouse; the engine evaluated it")
        return rows[0][0]


class Bench:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = Client(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            settings={"max_execution_time": 600},
            send_receive_timeout=600,
        )
        self.report = Report(config=cfg)

    def sql(self, query: str, **kwargs: Any) -> list[tuple[Any, ...]]:
        return self.client.execute(query, **kwargs)

    # -- setup -------------------------------------------------------------

    def setup(self) -> None:
        db = self.cfg.db
        if not self.cfg.keep:
            self.sql(f"DROP DATABASE IF EXISTS {db} SYNC")
        self.sql(f"CREATE DATABASE IF NOT EXISTS {db}")
        for ddl in (
            METRICS2_INPUT_TABLE_SQL(),
            METRICS2_TABLE_SQL(),
            METRICS2_INPUT_TO_METRICS_MV(),
            METRIC_SERIES2_TABLE_SQL(),
            METRICS2_INPUT_TO_METRIC_SERIES_MV(),
        ):
            self.sql(_unreplicated(ddl))
        granularity = self.cfg.agg_index_granularity
        try:
            self.sql(_unreplicated(METRICS2_AGG_TABLE_SQL(index_granularity=granularity)))
            self.report.codec_note = "time-series codecs accepted: " + ", ".join(
                f"{name}_arr {codec}" for name, codec in ARRAY_CODECS.items()
            )
        except Exception as exc:  # noqa: BLE001
            if "codec" not in str(exc).lower():
                raise
            fallback = dict.fromkeys(ARRAY_CODECS, "CODEC(ZSTD(3))")
            self.sql(_unreplicated(METRICS2_AGG_TABLE_SQL(codecs=fallback, index_granularity=granularity)))
            self.report.codec_note = f"time-series codecs rejected, arrays use ZSTD(3). Server said: {exc}"
        self.sql(METRICS2_INPUT_TO_METRICS_AGG_MV())

    def stop_merges(self) -> None:
        for table in TABLES:
            self.sql(f"SYSTEM STOP MERGES {self.cfg.db}.{table}")

    def optimize(self) -> None:
        for table in (*TABLES, SERIES_TABLE):
            self.sql(f"SYSTEM START MERGES {self.cfg.db}.{table}")
            self.sql(f"OPTIMIZE TABLE {self.cfg.db}.{table} FINAL", settings={"optimize_throw_if_noop": 0})

    # -- data --------------------------------------------------------------

    def generate(self) -> None:
        cfg = self.cfg
        points_per_chunk = cfg.chunk_minutes * 60 // cfg.scrape_seconds
        chunk = dt.timedelta(minutes=cfg.chunk_minutes)
        chunk_start = BASE_TIME
        started = time.monotonic()
        chunks = 0
        while chunk_start < cfg.date_to:
            self.sql(self._generate_sql(chunk_start, points_per_chunk))
            chunk_start += chunk
            chunks += 1
        rows = self.sql(f"SELECT count() FROM {cfg.db}.metrics2")[0][0]
        self.report.checks.append(
            f"generated {rows:,} points in {chunks} inserts of {cfg.chunk_minutes} min, {time.monotonic() - started:.1f} s"
        )

    def _generate_sql(self, chunk_start: dt.datetime, points_per_chunk: int) -> str:
        cfg = self.cfg
        return f"""
INSERT INTO {cfg.db}.metrics2_input
WITH
    number % {cfg.n_series} AS s,
    intDiv(number, {cfg.n_series}) AS p,
    toInt32(1 + intDiv(s, {cfg.metrics * cfg.series})) AS team,
    toUInt32(intDiv(s, {cfg.series}) % {cfg.metrics}) AS m,
    ['gauge', 'sum', 'histogram'][m % 3 + 1] AS mtype,
    {_ts(chunk_start)} + toIntervalSecond(p * {cfg.scrape_seconds}) AS ts,
    intDiv(toUnixTimestamp(ts), 3600) AS hour_idx,
    (toUnixTimestamp(ts) - {int(BASE_TIME.timestamp())}) * toFloat64(1 + s % 7) AS raw_counter,
    if(hour_idx % 37 = 0, raw_counter * 0.01, raw_counter) AS counter_value,
    concat('svc_', toString(s % 10)) AS service,
    CAST(map('host', concat('host-', toString(s % {cfg.series}))), 'Map(LowCardinality(String), String)') AS labels,
    CAST(map('region', ['eu', 'us'][s % 2 + 1]), 'Map(LowCardinality(String), String)') AS resource_labels
SELECT
    '' AS uuid,
    team AS team_id,
    concat('metric_', toString(m)) AS metric_name,
    cityHash64(team, m, s) AS series_fingerprint,
    cityHash64(resource_labels) AS resource_fingerprint,
    ts AS timestamp,
    ts AS observed_timestamp,
    ts + toIntervalDay(90) AS original_expiry_timestamp,
    service AS service_name,
    mtype AS metric_type,
    multiIf(mtype = 'gauge', 50 + 10 * sin(toFloat64(toUnixTimestamp(ts)) / 600 + s), mtype = 'sum', counter_value, 0.) AS value,
    toUInt64(1) AS count,
    if(mtype = 'histogram', [10., 50., 100., 500.], []) AS histogram_bounds,
    if(mtype = 'histogram', arrayMap(i -> toUInt64(counter_value * i / 4), [1, 2, 3, 4]), []) AS histogram_counts,
    if(number % 50 = 0, hex(cityHash64(number, 'trace')), '') AS trace_id,
    if(number % 50 = 0, hex(cityHash64(number, 'span')), '') AS span_id,
    toInt32(0) AS trace_flags,
    true AS has_labels,
    '' AS unit,
    'cumulative' AS aggregation_temporality,
    mtype = 'sum' AS is_monotonic,
    '' AS instrumentation_scope,
    resource_labels AS resource_attributes,
    labels AS attributes,
    toUInt32(s % 8) AS _partition,
    'clickhouse_metrics' AS _topic,
    toUInt64(number) AS _offset
FROM numbers({cfg.n_series * points_per_chunk})
"""

    def storage_report(self, state: str) -> None:
        db = self.cfg.db
        rows = self.sql(
            f"""
            SELECT table, sum(rows), count(), sum(bytes_on_disk), sum(data_compressed_bytes), sum(data_uncompressed_bytes)
            FROM system.parts WHERE database = '{db}' AND active AND table IN {TABLES}
            GROUP BY table ORDER BY table
            """
        )
        for table, n_rows, parts, on_disk, compressed, uncompressed in rows:
            self.report.storage.append(
                {
                    "table": table,
                    "state": state,
                    "rows": n_rows,
                    "parts": parts,
                    "bytes_on_disk": on_disk,
                    "compressed": compressed,
                    "uncompressed": uncompressed,
                }
            )
        columns = self.sql(
            f"""
            SELECT table, column, sum(column_data_compressed_bytes), sum(column_data_uncompressed_bytes)
            FROM system.parts_columns WHERE database = '{db}' AND active AND table IN {TABLES}
            GROUP BY table, column ORDER BY table, 3 DESC
            """
        )
        for table, column, compressed, uncompressed in columns:
            self.report.columns.append(
                {
                    "table": table,
                    "state": state,
                    "column": column,
                    "compressed": compressed,
                    "uncompressed": uncompressed,
                }
            )
        lengths = " OR ".join(
            f"length({name}_arr) != length(timestamp_arr)" for name, _ in POINT_ARRAY_COLUMNS if name != "timestamp"
        )
        misaligned = self.sql(f"SELECT count() FROM {db}.metrics2_agg WHERE {lengths}")[0][0]
        flat_points = self.sql(f"SELECT sum(length(timestamp_arr)), max(length(timestamp_arr)) FROM {db}.metrics2_agg")[
            0
        ]
        base_points = self.sql(f"SELECT count() FROM {db}.metrics2")[0][0]
        self.report.checks.append(
            f"[{state}] misaligned rows: {misaligned}; points metrics2={base_points:,} "
            f"metrics2_agg={flat_points[0]:,} ({'equal' if base_points == flat_points[0] else 'DIFFERENT'}); "
            f"longest array: {flat_points[1]}"
        )

    # -- queries -----------------------------------------------------------

    def capture_queries(self) -> None:
        """Fill `report.queries` with snuffle's SQL and its array rewrite."""
        end = self.cfg.date_to
        with Snuffle(self.cfg, self.client) as snuffle:
            for name, promql, step, hours in PROMQL_CASES:
                sql = snuffle.capture(promql, end - dt.timedelta(hours=hours), end, step)
                self.report.queries[name] = {"promql": promql, "metrics2": sql, "metrics2_agg": to_agg_sql(sql)}

    def run_matrix(self, state: str) -> None:
        for name, variants in self.report.queries.items():
            results: dict[str, list[list[Any]]] = {}
            timings: dict[str, Measurement] = {}
            for variant in TABLES:
                rows, measurement = self._time_query(name, variant, state, variants[variant])
                results[variant] = _normalise(rows)
                timings[variant] = measurement
            reference = results["metrics2"]
            for variant, measurement in timings.items():
                equal = "yes" if results[variant] == reference else "NO"
                if equal == "NO":
                    self.report.checks.append(
                        f"[{state}] {name}/{variant} differs from metrics2: {_first_diff(reference, results[variant])}"
                    )
                self.report.measurements.append(_with_equal(measurement, equal))

    def _time_query(self, name: str, variant: str, state: str, sql: str) -> tuple[list[tuple[Any, ...]], Measurement]:
        durations: list[float] = []
        rows: list[tuple[Any, ...]] = []
        query_id = ""
        for run in range(self.cfg.runs):
            query_id = f"bench-{state}-{name}-{variant}-{run}-{int(time.time() * 1000)}"
            started = time.perf_counter()
            rows = self.sql(sql, query_id=query_id, settings={"use_query_cache": 0})
            durations.append((time.perf_counter() - started) * 1000)
        progress = self.client.last_query.progress
        self.sql("SYSTEM FLUSH LOGS")
        log = self.sql(
            f"""
            SELECT memory_usage, ProfileEvents['SelectedMarks'], ProfileEvents['SelectedParts']
            FROM system.query_log WHERE query_id = '{query_id}' AND type = 'QueryFinish' LIMIT 1
            """
        )
        memory, marks, parts = log[0] if log else (0, 0, 0)
        return rows, Measurement(
            query=name,
            variant=variant,
            state=state,
            median_ms=statistics.median(durations),
            min_ms=min(durations),
            read_rows=progress.rows,
            read_bytes=progress.bytes,
            memory_bytes=memory,
            selected_marks=marks,
            selected_parts=parts,
            granules=_granules(self._explain(sql)),
            rows_returned=len(rows),
            equal="",
        )

    def _explain(self, sql: str) -> str:
        rows = self.sql(f"EXPLAIN indexes = 1 {sql}")
        return "\n".join(row[0] for row in rows)


def _with_equal(measurement: Measurement, equal: str) -> Measurement:
    return Measurement(**{**measurement.__dict__, "equal": equal})


def _granules(explain: str) -> str:
    return " | ".join(line.strip() for line in explain.splitlines() if "Granules:" in line)


def _normalise_cell(cell: Any) -> Any:
    if isinstance(cell, float):
        return float(f"{cell:.9g}")
    if isinstance(cell, dt.datetime):
        return cell.replace(tzinfo=None).isoformat()
    if isinstance(cell, (list, tuple)):
        return sorted(str(_normalise_cell(item)) for item in cell)
    return cell


def _normalise(rows: Sequence[tuple[Any, ...]]) -> list[list[Any]]:
    return sorted(([_normalise_cell(cell) for cell in row] for row in rows), key=repr)


def _first_diff(reference: list[list[Any]], other: list[list[Any]]) -> str:
    if len(reference) != len(other):
        return f"row count {len(reference)} vs {len(other)}"
    for left, right in zip(reference, other):
        if left != right:
            return f"{left!r} vs {right!r}"
    return "no row differs"


def _fmt_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def render(report: Report) -> str:
    cfg = report.config
    out: list[str] = []
    out.append("# metrics2 vs metrics2_agg with snuffle range queries\n")
    out.append(
        f"- series: {cfg.n_series} ({cfg.teams} teams × {cfg.metrics} metrics × {cfg.series}); "
        f"scrape {cfg.scrape_seconds} s; {cfg.days} days; insert chunk {cfg.chunk_minutes} min; "
        f"{cfg.runs} runs per query; max_threads {cfg.threads}"
    )
    out.append(
        f"- server: {cfg.host}:{cfg.port}, database `{cfg.db}`; snuffle: `{cfg.snuffle_bin}`; "
        f"metrics2_agg index_granularity {cfg.agg_index_granularity}"
    )
    out.append(f"- codecs: {report.codec_note}\n")
    out.append("## Checks\n")
    out.extend(f"- {check}" for check in report.checks)
    out.append("\n## Storage\n")
    out.append("| table | state | rows | parts | on disk | compressed | uncompressed | ratio |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for row in report.storage:
        ratio = row["uncompressed"] / row["compressed"] if row["compressed"] else 0
        out.append(
            f"| {row['table']} | {row['state']} | {row['rows']:,} | {row['parts']} | {_fmt_bytes(row['bytes_on_disk'])} "
            f"| {_fmt_bytes(row['compressed'])} | {_fmt_bytes(row['uncompressed'])} | {ratio:.1f}x |"
        )
    out.append("\n### Largest columns (merged)\n")
    out.append("| table | column | compressed | uncompressed |")
    out.append("|---|---|---:|---:|")
    merged = [c for c in report.columns if c["state"] == "merged"]
    for table in TABLES:
        for col in [c for c in merged if c["table"] == table][:8]:
            out.append(
                f"| {table} | {col['column']} | {_fmt_bytes(col['compressed'])} | {_fmt_bytes(col['uncompressed'])} |"
            )
    out.append("\n## PromQL cases\n")
    out.append("| query | PromQL | step | range |")
    out.append("|---|---|---:|---:|")
    for name, promql, step, hours in PROMQL_CASES:
        if name in report.queries:
            out.append(f"| {name} | `{promql}` | {step} s | {hours} h |")
    out.append("\n## Queries\n")
    out.append(
        "| query | variant | state | median ms | min ms | read rows | read bytes | peak memory | marks | parts | rows | equal |"
    )
    out.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for m in report.measurements:
        out.append(
            f"| {m.query} | {m.variant} | {m.state} | {m.median_ms:.1f} | {m.min_ms:.1f} | {m.read_rows:,} "
            f"| {_fmt_bytes(m.read_bytes)} | {_fmt_bytes(m.memory_bytes)} | {m.selected_marks} | {m.selected_parts} "
            f"| {m.rows_returned} | {m.equal} |"
        )
    out.append("\n## Granules selected\n")
    for m in report.measurements:
        if m.state == "merged" and m.granules:
            out.append(f"- {m.query}/{m.variant}: {m.granules}")
    out.append("\n## Captured SQL\n")
    for name, variants in report.queries.items():
        out.append(f"### {name}: `{variants['promql']}`\n")
        for variant in TABLES:
            out.append(f"**{variant}**\n\n```sql\n{variants[variant]}\n```\n")
    return "\n".join(out)


def parse_args(argv: Sequence[str]) -> Config:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=settings.CLICKHOUSE_LOGS_CLUSTER_HOST)
    parser.add_argument("--port", type=int, default=int(settings.CLICKHOUSE_LOGS_CLUSTER_PORT))
    parser.add_argument("--user", default=settings.CLICKHOUSE_LOGS_CLUSTER_USER)
    parser.add_argument("--password", default=settings.CLICKHOUSE_LOGS_CLUSTER_PASSWORD)
    parser.add_argument("--teams", type=int, default=2)
    parser.add_argument("--metrics", type=int, default=12, help="metric names per team; must be at least 3")
    parser.add_argument("--series", type=int, default=50, help="series per metric")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--scrape-seconds", type=int, default=15)
    parser.add_argument("--chunk-minutes", type=int, default=15)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--skip-generate", action="store_true", help="reuse the data of a previous --keep run")
    parser.add_argument("--keep", action="store_true", help="do not drop the scratch database first")
    parser.add_argument("--snuffle-bin", default=os.environ.get("SNUFFLE_BIN", "snuffle"), help="snuffle binary")
    parser.add_argument("--snuffle-port", type=int, default=19091)
    parser.add_argument("--agg-index-granularity", type=int, default=128, help="index_granularity of metrics2_agg")
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--out", dest="out_path", default=None, help="write the markdown report here too")
    args = parser.parse_args(argv)
    if args.metrics < 3:
        parser.error("--metrics must be at least 3 (gauge, sum and histogram)")
    if args.days < 2:
        parser.error("--days must be at least 2 so the 24 h cases have a full day of data")
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    if db == settings.CLICKHOUSE_DATABASE:
        parser.error("set CLICKHOUSE_LOGS_DATABASE to a scratch database, not the main one")
    return Config(db=db, **vars(args))


def main(argv: Sequence[str]) -> int:
    cfg = parse_args(argv)
    bench = Bench(cfg)
    if not cfg.skip_generate:
        bench.setup()
        bench.stop_merges()
        bench.generate()
    bench.capture_queries()
    if not cfg.skip_generate:
        bench.storage_report("unmerged")
        bench.run_matrix("unmerged")
        bench.optimize()
    bench.storage_report("merged")
    bench.run_matrix("merged")
    text = render(bench.report)
    sys.stdout.write(text + "\n")
    if cfg.out_path:
        with open(cfg.out_path, "w") as handle:
            handle.write(text)
    if cfg.json_path:
        payload = {
            "config": cfg.__dict__,
            "storage": bench.report.storage,
            "columns": bench.report.columns,
            "measurements": [m.__dict__ for m in bench.report.measurements],
            "queries": bench.report.queries,
            "checks": bench.report.checks,
        }
        with open(cfg.json_path, "w") as handle:
            json.dump(payload, handle, indent=2, default=str)
    return 0 if all(m.equal == "yes" for m in bench.report.measurements) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
