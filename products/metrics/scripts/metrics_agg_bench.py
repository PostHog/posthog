#!/usr/bin/env python3
"""Benchmark the `metrics2_agg` array layout against `metrics2`.

The script creates both tables, the MVs that fill them from `metrics2_input`,
and the `metrics2_flat` ARRAY JOIN view in a scratch database. It generates
synthetic points server-side, inserts them in small chunks so `metrics2_agg`
gets partial rows, and runs the query shapes the metrics readers use against
`metrics2`, the view, and (for gauges) the arrays directly. It runs the matrix
twice: with merges stopped, and after `OPTIMIZE TABLE ... FINAL`. It checks that
every variant returns the same rows and prints a markdown report.

Usage, from the repo root with the dev stack running:

    CLICKHOUSE_LOGS_DATABASE=metrics_bench python products/metrics/scripts/metrics_agg_bench.py

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("DEBUG", "1")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from clickhouse_driver import Client  # noqa: E402

from posthog.clickhouse.metrics import (  # noqa: E402
    METRICS2_AGG_TABLE_SQL,
    METRICS2_FLAT_INDEXED_VIEW_SQL,
    METRICS2_FLAT_VIEW_SQL,
    METRICS2_INPUT_TABLE_SQL,
    METRICS2_INPUT_TO_METRICS_AGG_MV,
    METRICS2_INPUT_TO_METRICS_MV,
    METRICS2_TABLE_SQL,
)
from posthog.clickhouse.metrics.metrics_agg import ARRAY_CODECS, POINT_ARRAY_COLUMNS  # noqa: E402

BASE_TIME = dt.datetime(2026, 9, 1, 0, 0, tzinfo=dt.UTC)
ROW_LIMIT = 10_000
TABLES = ("metrics2", "metrics2_agg")


def _unreplicated(sql: str) -> str:
    return re.sub(r"Replicated(\w*MergeTree)\('[^']*',\s*'[^']*'\)", r"\1()", sql)


def _ts(value: dt.datetime) -> str:
    return f"toDateTime64('{value.strftime('%Y-%m-%d %H:%M:%S')}', 6, 'UTC')"


def _hour(value: dt.datetime) -> str:
    return f"toDateTime('{value.replace(minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')}', 'UTC')"


def _time_range(date_from: dt.datetime, date_to: dt.datetime) -> str:
    return (
        f"timestamp >= {_ts(date_from)} AND timestamp < {_ts(date_to)} "
        f"AND time_bucket >= {_hour(date_from)} AND time_bucket <= {_hour(date_to)}"
    )


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
    explains: dict[str, str] = field(default_factory=dict)
    checks: list[str] = field(default_factory=list)


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
        for ddl in (METRICS2_INPUT_TABLE_SQL(), METRICS2_TABLE_SQL(), METRICS2_INPUT_TO_METRICS_MV()):
            self.sql(_unreplicated(ddl))
        try:
            self.sql(_unreplicated(METRICS2_AGG_TABLE_SQL()))
            self.report.codec_note = "time-series codecs accepted: " + ", ".join(
                f"{name}_arr {codec}" for name, codec in ARRAY_CODECS.items()
            )
        except Exception as exc:  # noqa: BLE001
            if "codec" not in str(exc).lower():
                raise
            fallback = dict.fromkeys(ARRAY_CODECS, "CODEC(ZSTD(3))")
            self.sql(_unreplicated(METRICS2_AGG_TABLE_SQL(codecs=fallback)))
            self.report.codec_note = f"time-series codecs rejected, arrays use ZSTD(3). Server said: {exc}"
        self.sql(METRICS2_INPUT_TO_METRICS_AGG_MV())
        self.sql(METRICS2_FLAT_VIEW_SQL())
        self.sql(METRICS2_FLAT_INDEXED_VIEW_SQL())

    def stop_merges(self) -> None:
        for table in TABLES:
            self.sql(f"SYSTEM STOP MERGES {self.cfg.db}.{table}")

    def optimize(self) -> None:
        for table in TABLES:
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
        maps = "CAST(map(), 'Map(LowCardinality(String), String)')"
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
    if(hour_idx % 37 = 0, raw_counter * 0.01, raw_counter) AS counter_value
SELECT
    '' AS uuid,
    team AS team_id,
    concat('metric_', toString(m)) AS metric_name,
    cityHash64(team, m, s) AS series_fingerprint,
    cityHash64(s % 10) AS resource_fingerprint,
    ts AS timestamp,
    ts AS observed_timestamp,
    ts + toIntervalDay(90) AS original_expiry_timestamp,
    concat('svc_', toString(s % 10)) AS service_name,
    mtype AS metric_type,
    multiIf(mtype = 'gauge', 50 + 10 * sin(toFloat64(toUnixTimestamp(ts)) / 600 + s), mtype = 'sum', counter_value, 0.) AS value,
    toUInt64(1) AS count,
    if(mtype = 'histogram', [10., 50., 100., 500.], []) AS histogram_bounds,
    if(mtype = 'histogram', arrayMap(i -> toUInt64(counter_value * i / 4), [1, 2, 3, 4]), []) AS histogram_counts,
    if(number % 50 = 0, hex(cityHash64(number, 'trace')), '') AS trace_id,
    if(number % 50 = 0, hex(cityHash64(number, 'span')), '') AS span_id,
    toInt32(0) AS trace_flags,
    false AS has_labels,
    '' AS unit,
    'cumulative' AS aggregation_temporality,
    mtype = 'sum' AS is_monotonic,
    '' AS instrumentation_scope,
    {maps} AS resource_attributes,
    {maps} AS attributes,
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
                {"table": table, "state": state, "column": column, "compressed": compressed, "uncompressed": uncompressed}
            )
        lengths = " OR ".join(
            f"length({name}_arr) != length(timestamp_arr)" for name, _ in POINT_ARRAY_COLUMNS if name != "timestamp"
        )
        misaligned = self.sql(f"SELECT count() FROM {db}.metrics2_agg WHERE {lengths}")[0][0]
        flat_points = self.sql(f"SELECT sum(length(timestamp_arr)), max(length(timestamp_arr)) FROM {db}.metrics2_agg")[0]
        base_points = self.sql(f"SELECT count() FROM {db}.metrics2")[0][0]
        self.report.checks.append(
            f"[{state}] misaligned rows: {misaligned}; points metrics2={base_points:,} "
            f"metrics2_agg={flat_points[0]:,} ({'equal' if base_points == flat_points[0] else 'DIFFERENT'}); "
            f"longest array: {flat_points[1]}"
        )

    # -- queries -----------------------------------------------------------

    def queries(self) -> dict[str, dict[str, str]]:
        """Return `{query_name: {variant: sql}}` for every benchmark query."""
        cfg = self.cfg
        db = cfg.db
        end = cfg.date_to
        six_h = end - dt.timedelta(hours=6)
        day = end - dt.timedelta(hours=24)
        base = f"{db}.metrics2"
        views = {"metrics2_flat": f"{db}.metrics2_flat", "metrics2_flat_idx": f"{db}.metrics2_flat_idx"}

        fingerprints = [
            str(row[0])
            for row in self.sql(
                f"SELECT DISTINCT series_fingerprint FROM {base} WHERE team_id = 1 AND metric_name = 'metric_0' "
                f"AND {_time_range(six_h, end)} ORDER BY series_fingerprint LIMIT 10"
            )
        ]
        trace_row = self.sql(
            f"SELECT trace_id FROM {base} WHERE team_id = 1 AND metric_name = 'metric_1' AND trace_id != '' "
            f"AND {_time_range(six_h, end)} ORDER BY timestamp DESC LIMIT 1"
        )
        trace_id = trace_row[0][0] if trace_row else ""
        sparkline_names = ", ".join(f"'metric_{m}'" for m in range(0, cfg.metrics, 3))
        window_start = int(day.timestamp())

        def gauge(t: str, interval: str, date_from: dt.datetime, extra: str = "") -> str:
            return f"""
SELECT time, sum(series_value) AS value, groupUniqArray(series_fingerprint) AS series_fingerprints
FROM (
    SELECT toStartOfInterval(timestamp, {interval}) AS time, series_fingerprint, argMax(value, timestamp) AS series_value
    FROM {t}
    WHERE team_id = 1 AND metric_name = 'metric_0' AND {_time_range(date_from, end)} AND metric_type = 'gauge' {extra}
    GROUP BY time, series_fingerprint
) AS s
GROUP BY time ORDER BY time ASC LIMIT {ROW_LIMIT}"""

        def gauge_native(interval: str, date_from: dt.datetime, extra: str = "") -> str:
            return f"""
SELECT time, sum(series_value) AS value, groupUniqArray(series_fingerprint) AS series_fingerprints
FROM (
    SELECT series_fingerprint, p.1 AS time, argMax(p.3, p.2) AS series_value
    FROM {db}.metrics2_agg
    ARRAY JOIN arrayFilter(
        t -> t.2 >= {_ts(date_from)} AND t.2 < {_ts(end)},
        arrayZip(arrayMap(x -> toStartOfInterval(x, {interval}), timestamp_arr), timestamp_arr, value_arr)
    ) AS p
    WHERE team_id = 1 AND metric_name = 'metric_0'
      AND time_bucket >= {_hour(date_from)} AND time_bucket <= {_hour(end)} AND metric_type = 'gauge' {extra}
    GROUP BY series_fingerprint, time
) AS s
GROUP BY time ORDER BY time ASC LIMIT {ROW_LIMIT}"""

        def counter(t: str) -> str:
            scan_from = six_h - dt.timedelta(minutes=5)
            return f"""
SELECT toStartOfInterval(sample_timestamp, INTERVAL 5 MINUTE) AS time, sum(contribution) / 300 AS value,
       groupUniqArray(series_fingerprint) AS series_fingerprints
FROM (
    SELECT timestamp AS sample_timestamp, series_fingerprint,
        multiIf(aggregation_temporality = 'delta', value, isNull(prev_value), NULL,
                value >= assumeNotNull(prev_value), value - assumeNotNull(prev_value), value) AS contribution
    FROM (
        SELECT timestamp, series_fingerprint, value, aggregation_temporality,
            lagInFrame(toNullable(value)) OVER (PARTITION BY series_fingerprint ORDER BY timestamp ASC
                ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING) AS prev_value
        FROM {t}
        WHERE team_id = 1 AND metric_name = 'metric_1' AND {_time_range(scan_from, end)} AND metric_type = 'sum'
    )
) AS s
WHERE sample_timestamp >= {_ts(six_h)}
GROUP BY time HAVING isNotNull(value) ORDER BY time ASC LIMIT {ROW_LIMIT}"""

        def histogram(t: str) -> str:
            scan_from = six_h - dt.timedelta(minutes=5)
            return f"""
SELECT toStartOfInterval(sample_timestamp, INTERVAL 5 MINUTE) AS time, any(histogram_bounds) AS bounds,
       groupUniqArray(histogram_bounds) AS bounds_variants, sumForEach(contribution_counts) AS counts,
       groupUniqArray(series_fingerprint) AS series_fingerprints
FROM (
    SELECT timestamp AS sample_timestamp, series_fingerprint, histogram_bounds,
        multiIf(aggregation_temporality = 'delta', counts_f,
                empty(prev_counts), arrayMap(x -> 0.0, counts_f),
                length(prev_counts) != length(counts_f), counts_f,
                arrayAll((c, p) -> c >= p, counts_f, prev_counts), arrayMap((c, p) -> c - p, counts_f, prev_counts),
                counts_f) AS contribution_counts
    FROM (
        SELECT timestamp, series_fingerprint, aggregation_temporality, histogram_bounds,
            arrayMap(x -> toFloat64(x), histogram_counts) AS counts_f,
            lagInFrame(arrayMap(x -> toFloat64(x), histogram_counts)) OVER (PARTITION BY series_fingerprint
                ORDER BY timestamp ASC ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING) AS prev_counts
        FROM {t}
        WHERE team_id = 1 AND metric_name = 'metric_2' AND {_time_range(scan_from, end)}
          AND notEmpty(histogram_counts) AND metric_type = 'histogram'
    )
) AS s
WHERE sample_timestamp >= {_ts(six_h)}
GROUP BY time ORDER BY time ASC LIMIT {ROW_LIMIT}"""

        def samples(t: str, trace_filter: str) -> str:
            return f"""
SELECT team_id, metric_name, series_fingerprint, timestamp, value, count, trace_id, span_id, metric_type
FROM {t}
WHERE team_id = 1 AND metric_name = 'metric_1' AND {_time_range(six_h, end)} {trace_filter}
ORDER BY timestamp DESC, series_fingerprint LIMIT 100"""

        def sparkline(t: str) -> str:
            return f"""
SELECT metric_name AS name,
       toDateTime(intDiv(toUnixTimestamp(timestamp) - {window_start}, 3600) * 3600 + {window_start}) AS bucket_start,
       avg(value) AS bucket_value
FROM {t}
WHERE team_id = 1 AND timestamp > {_ts(day)} AND time_bucket >= {_hour(day)} AND metric_name IN ({sparkline_names})
GROUP BY name, bucket_start ORDER BY name, bucket_start"""

        in_list = f"AND series_fingerprint IN ({', '.join(fingerprints)})"

        def variants(build: Callable[[str], str]) -> dict[str, str]:
            return {"metrics2": build(base), **{name: build(table) for name, table in views.items()}}

        return {
            "gauge_5m_6h": {
                **variants(lambda t: gauge(t, "INTERVAL 5 MINUTE", six_h)),
                "native": gauge_native("INTERVAL 5 MINUTE", six_h),
            },
            "gauge_1h_24h": {
                **variants(lambda t: gauge(t, "INTERVAL 1 HOUR", day)),
                "native": gauge_native("INTERVAL 1 HOUR", day),
            },
            "gauge_filtered_5m_6h": {
                **variants(lambda t: gauge(t, "INTERVAL 5 MINUTE", six_h, in_list)),
                "native": gauge_native("INTERVAL 5 MINUTE", six_h, in_list),
            },
            "counter_rate_5m_6h": variants(counter),
            "histogram_5m_6h": variants(histogram),
            "samples_recent": variants(lambda t: samples(t, "")),
            "samples_trace_id": variants(lambda t: samples(t, f"AND trace_id = '{trace_id}'")),
            "sparkline_24h": variants(sparkline),
            "select_1": variants(lambda t: f"SELECT 1 FROM {t} LIMIT 1"),
        }

    def run_matrix(self, state: str) -> None:
        for name, variants in self.queries().items():
            results: dict[str, list[list[Any]]] = {}
            timings: dict[str, Measurement] = {}
            for variant, sql in variants.items():
                rows, measurement = self._time_query(name, variant, state, sql)
                results[variant] = _normalise(rows)
                timings[variant] = measurement
                if state == "merged":
                    self.report.explains[f"{name}/{variant}"] = self._explain(sql)
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
            rows = self.sql(sql, query_id=query_id, settings={"use_query_cache": 0, "max_threads": self.cfg.threads})
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
        granules = ""
        if variant != "native" or state == "merged":
            granules = _granules(self._explain(sql))
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
            granules=granules,
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
    out.append("# metrics2 vs metrics2_agg benchmark\n")
    out.append(
        f"- series: {cfg.n_series} ({cfg.teams} teams × {cfg.metrics} metrics × {cfg.series}); "
        f"scrape {cfg.scrape_seconds} s; {cfg.days} days; insert chunk {cfg.chunk_minutes} min; "
        f"{cfg.runs} runs per query; max_threads {cfg.threads}"
    )
    out.append(f"- server: {cfg.host}:{cfg.port}, database `{cfg.db}`")
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
            out.append(f"| {table} | {col['column']} | {_fmt_bytes(col['compressed'])} | {_fmt_bytes(col['uncompressed'])} |")
    out.append("\n## Queries\n")
    out.append("| query | variant | state | median ms | min ms | read rows | read bytes | peak memory | marks | parts | rows | equal |")
    out.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for m in report.measurements:
        out.append(
            f"| {m.query} | {m.variant} | {m.state} | {m.median_ms:.1f} | {m.min_ms:.1f} | {m.read_rows:,} "
            f"| {_fmt_bytes(m.read_bytes)} | {_fmt_bytes(m.memory_bytes)} | {m.selected_marks} | {m.selected_parts} "
            f"| {m.rows_returned} | {m.equal} |"
        )
    out.append("\n## Granules selected (merged)\n")
    for m in report.measurements:
        if m.state == "merged" and m.granules:
            out.append(f"- {m.query}/{m.variant}: {m.granules}")
    out.append("\n## EXPLAIN indexes = 1 for the view variants (merged)\n")
    for key, text in report.explains.items():
        if not key.endswith("/metrics2"):
            out.append(f"### {key}\n\n```\n{text}\n```\n")
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
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--out", dest="out_path", default=None, help="write the markdown report here too")
    args = parser.parse_args(argv)
    if args.metrics < 3:
        parser.error("--metrics must be at least 3 (gauge, sum and histogram)")
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
            "checks": bench.report.checks,
        }
        with open(cfg.json_path, "w") as handle:
            json.dump(payload, handle, indent=2, default=str)
    return 0 if all(m.equal == "yes" for m in bench.report.measurements) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
