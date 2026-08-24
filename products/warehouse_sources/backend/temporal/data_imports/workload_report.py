"""Per-run workload self-reporting for warehouse sync and repartition activities.

Each reporting activity periodically writes what it is doing — phase, current in-memory buffer, process
RSS, and the peaks of both — to the warehouse Redis, keyed by run. The value outlives the worker, so
when a worker dies silently the retry can read the dead attempt's last report, and the reports of
everything else that was running on the same pod, and attach them to the `dwh_pod_heartbeat_timeout`
telemetry event.

Observe-only for now: nothing acts on these reports. They exist to answer, from production data, the
questions the OOM-classification work needs answered before it can pick thresholds — what phase do
silent deaths happen in, how big was the dead attempt's own working set, and how big were its
co-tenants' at that moment. A worker cannot attribute shared-process memory per activity, but it knows
its own buffer exactly (the same accounting dynamic chunking already uses), which is the per-activity
signal at-rest partition sizes cannot provide.

The write path mirrors `row_tracking.py`: per-run keys with a TTL on the warehouse Redis, plus a
per-host set so co-tenants are discoverable. Everything here is best-effort — a reporting failure
must never affect a sync.
"""

from __future__ import annotations

import json
import time
import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Any

from django.conf import settings

from structlog import get_logger

from posthog.redis import get_client
from posthog.web_memory_sampler import current_rss_mb

LOGGER = get_logger(__name__)

# Keys live longer than any plausible gap between a death and its retry (heartbeat timeout is minutes),
# but short enough that crashed runs don't accumulate. The host set carries the same TTL, refreshed on
# every sample, so it can only outlive its members briefly.
WORKLOAD_REPORT_TTL_SECONDS = 2 * 60 * 60

_RUN_KEY_PREFIX = "posthog:data_warehouse:workload:run:"
_HOST_KEY_PREFIX = "posthog:data_warehouse:workload:host:"

_current_reporter: ContextVar[WorkloadReporter | None] = ContextVar("dwh_workload_reporter", default=None)


def workload_report_interval_seconds() -> float:
    return float(getattr(settings, "DATA_WAREHOUSE_WORKLOAD_REPORT_INTERVAL_SECONDS", 30))


def workload_high_watermark_bytes() -> int:
    return int(getattr(settings, "DATA_WAREHOUSE_WORKLOAD_HIGH_WATERMARK_BYTES", 500_000_000))


def run_key(run_id: str) -> str:
    return f"{_RUN_KEY_PREFIX}{run_id}"


def host_key(host: str) -> str:
    return f"{_HOST_KEY_PREFIX}{host}"


def _redis_client() -> Any | None:
    host = getattr(settings, "DATA_WAREHOUSE_REDIS_HOST", None)
    port = getattr(settings, "DATA_WAREHOUSE_REDIS_PORT", None)
    if not host or not port:
        return None
    return get_client(f"redis://{host}:{port}/")


def report_phase(phase: str) -> None:
    """Record the current phase from anywhere inside a reporting activity; no-op outside one."""
    reporter = _current_reporter.get()
    if reporter is not None:
        reporter.set_phase(phase)


def report_buffer_bytes(buffer_bytes: int) -> None:
    """Record the activity's current in-memory buffer from anywhere inside it; no-op outside one."""
    reporter = _current_reporter.get()
    if reporter is not None:
        reporter.set_buffer_bytes(buffer_bytes)


class WorkloadReporter:
    """Samples one activity's self-declared workload into Redis on a background thread.

    Thread-safe by construction: the hook setters only assign ints/strings under a lock, and the
    sampling thread does all Redis I/O. The sync path never blocks on reporting.
    """

    def __init__(
        self,
        *,
        team_id: int,
        schema_id: str,
        run_id: str,
        host: str,
        initial_phase: str = "extract",
        attempt: int = 1,
    ) -> None:
        self._team_id = team_id
        self._schema_id = schema_id
        self._run_id = run_id
        self._host = host
        self._attempt = attempt
        self._lock = threading.Lock()
        self._phase = initial_phase
        self._buffer_bytes = 0
        self._peak_buffer_bytes = 0
        self._peak_rss_bytes = 0
        self._started_at = time.time()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = False
        self._superseded = False

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self._phase = phase

    def set_buffer_bytes(self, buffer_bytes: int) -> None:
        with self._lock:
            self._buffer_bytes = buffer_bytes
            self._peak_buffer_bytes = max(self._peak_buffer_bytes, buffer_bytes)

    def start(self) -> None:
        interval = workload_report_interval_seconds()
        if interval <= 0:
            return
        self._enabled = True
        self._thread = threading.Thread(
            target=self._run, args=(interval,), name=f"dwh-workload-report-{self._run_id[:8]}", daemon=True
        )
        self._thread.start()

    def stop(self, *, outcome: str = "completed") -> None:
        """Stop sampling and drop this run from its host's co-tenant set.

        The run key is left to expire naturally: a just-finished neighbour is still relevant context
        for a death that happens moments later, but it should no longer be listed as running.

        A reporter that never started (interval <= 0, the fleet kill switch) emits nothing here
        either — off must mean off. A superseded reporter (a zombie attempt outlived by its retry)
        writes nothing and removes nothing: the srem and final sample belong to the live attempt now
        sharing this run's key. Its watermark event still fires — the peak it observed is real.
        """
        if not self._enabled:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        try:
            redis = _redis_client()
            if redis is not None and not self._superseded:
                self._write_sample(redis, final=True)
                if not self._superseded:
                    redis.srem(host_key(self._host), self._run_id)
        except Exception:
            LOGGER.debug("workload_report_stop_failed", run_id=self._run_id, exc_info=True)
        self._capture_high_watermark(outcome)

    def _capture_high_watermark(self, outcome: str) -> None:
        """Emit one event for runs whose peak buffer crossed the high-watermark threshold.

        Deaths are enriched via Redis; this captures the tail of runs that exited through Python —
        cleanly or by raising — which is what calibrates thresholds (how big does a working set get
        without silently killing the pod?). `outcome` distinguishes the two so a failed run cannot
        contaminate a survivors-only distribution. Emitting only above the watermark keeps this to
        the rare, high-signal tail instead of an event per sync.
        """
        try:
            threshold = workload_high_watermark_bytes()
            if threshold <= 0 or self._peak_buffer_bytes < threshold:
                return
            import posthoganalytics  # noqa: PLC0415 — keeps the analytics client off this module's import path

            posthoganalytics.capture(
                "dwh_workload_high_watermark",
                distinct_id=None,
                properties={
                    "team_id": self._team_id,
                    "schema_id": self._schema_id,
                    "run_id": self._run_id,
                    "host": self._host,
                    "phase": self._phase,
                    "peak_buffer_bytes": self._peak_buffer_bytes,
                    "peak_rss_bytes": self._peak_rss_bytes or None,
                    "duration_seconds": round(time.time() - self._started_at, 1),
                    "outcome": outcome,
                },
            )
        except Exception:
            LOGGER.debug("workload_report_watermark_failed", run_id=self._run_id, exc_info=True)

    def _run(self, interval: float) -> None:
        # First sample immediately: a fast OOM can kill the pod within the first interval, and a
        # killed attempt never reaches stop() — without this, the quickest deaths (the most
        # interesting ones) would have no report at all.
        try:
            redis = _redis_client()
            if redis is not None:
                self._write_sample(redis)
        except Exception:
            LOGGER.debug("workload_report_sample_failed", run_id=self._run_id, exc_info=True)
        while not self._stop_event.wait(interval):
            try:
                redis = _redis_client()
                if redis is None:
                    return
                self._write_sample(redis)
            except Exception:
                # Best-effort: never let reporting noise surface anywhere near the sync.
                LOGGER.debug("workload_report_sample_failed", run_id=self._run_id, exc_info=True)

    def _write_sample(self, redis: Any, *, final: bool = False) -> None:
        # Attempts share the run key, and a heartbeat-timed-out attempt keeps running as a zombie
        # while its retry reports under the same key. The higher attempt owns the key: a reporter
        # that finds a newer attempt's report there goes permanently silent instead of fighting over
        # it. The read-then-write pair isn't atomic, but a losing interleave only survives until the
        # next sample on either side — acceptable for best-effort telemetry.
        existing = _parse_report(redis.get(run_key(self._run_id)))
        if existing is not None and int(existing.get("attempt") or 0) > self._attempt:
            self._superseded = True
            self._stop_event.set()
            return
        rss_mb = current_rss_mb()
        rss_bytes = int(rss_mb * 1024 * 1024) if rss_mb is not None else None
        with self._lock:
            if rss_bytes is not None:
                self._peak_rss_bytes = max(self._peak_rss_bytes, rss_bytes)
            payload = {
                "run_id": self._run_id,
                "team_id": self._team_id,
                "schema_id": self._schema_id,
                "host": self._host,
                "attempt": self._attempt,
                "phase": "finished" if final else self._phase,
                # A run that reached teardown released its buffer while unwinding, so the last
                # value the hooks saw is stale — a rewrite that raised mid-flush still reports the
                # batch it was writing. Zero it for the same reason the phase becomes "finished":
                # this run holds nothing now. `peak_buffer_bytes` keeps the real high-water mark,
                # which is what blame is judged on. A run that died with its pod never writes a
                # final sample at all, so this cannot erase a death's own last words.
                "buffer_bytes": 0 if final else self._buffer_bytes,
                "peak_buffer_bytes": self._peak_buffer_bytes,
                "rss_bytes": rss_bytes,
                "peak_rss_bytes": self._peak_rss_bytes or None,
                "started_at": self._started_at,
                "ts": time.time(),
            }
        redis.setex(run_key(self._run_id), WORKLOAD_REPORT_TTL_SECONDS, json.dumps(payload))
        if not final:
            host = host_key(self._host)
            redis.sadd(host, self._run_id)
            redis.expire(host, WORKLOAD_REPORT_TTL_SECONDS)


@contextmanager
def _reporting_span(
    team_id: int, schema_id: str, run_id: str, host: str, initial_phase: str, attempt: int
) -> Iterator[WorkloadReporter]:
    """Shared lifecycle of both public managers: construct, start, bind the hooks, unbind.

    Exit classification and the stop() call stay with the variants — they must live in the frame
    directly around the user's block, because an inner finally unwinds before any outer handler.
    """
    reporter = WorkloadReporter(
        team_id=team_id, schema_id=schema_id, run_id=run_id, host=host, initial_phase=initial_phase, attempt=attempt
    )
    reporter.start()
    token = _current_reporter.set(reporter)
    try:
        yield reporter
    finally:
        _current_reporter.reset(token)


@contextmanager
def workload_reporting(
    *, team_id: int, schema_id: str, run_id: str, host: str, initial_phase: str = "extract", attempt: int = 1
) -> Iterator[None]:
    """Run the wrapped block with a live workload reporter bound for `report_phase`/`report_buffer_bytes`.

    Fully inert when the interval setting is <= 0 or the warehouse Redis is unconfigured. For async
    callers use `aworkload_reporting`, which keeps the blocking teardown off the event loop.

    `attempt` disambiguates Temporal retries sharing one `run_id`: the newest attempt owns the run
    key, and an older zombie that discovers a newer report under it stops writing (see
    `_write_sample`). Callers without retry semantics can leave the default.
    """
    with _reporting_span(team_id, schema_id, run_id, host, initial_phase, attempt) as reporter:
        # Outcome must be classified in the same frame that calls stop(): an inner finally unwinds
        # before any outer except could observe the exception.
        outcome = "completed"
        try:
            yield
        except BaseException:
            outcome = "raised"
            raise
        finally:
            reporter.stop(outcome=outcome)


@asynccontextmanager
async def aworkload_reporting(
    *, team_id: int, schema_id: str, run_id: str, host: str, initial_phase: str = "extract", attempt: int = 1
) -> AsyncIterator[None]:
    """Async variant of `workload_reporting` for the import activity.

    `stop()` joins the sampler thread and talks to Redis synchronously; run inline it would stall the
    activity's event loop (and its heartbeats) for up to the join timeout, so it is offloaded.
    """
    with _reporting_span(team_id, schema_id, run_id, host, initial_phase, attempt) as reporter:
        outcome = "completed"
        try:
            yield
        except BaseException:
            outcome = "raised"
            raise
        finally:
            await asyncio.to_thread(reporter.stop, outcome=outcome)


def _parse_report(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def read_workload_reports(host: str) -> list[dict[str, Any]]:
    """Last self-reports of every run recorded as running on `host`, freshest first.

    Read on the retry after a silent death, so `host` is the dead pod. Never raises; an unreadable
    Redis just means no enrichment.
    """
    try:
        redis = _redis_client()
        if redis is None:
            return []
        run_ids = [rid.decode() if isinstance(rid, bytes) else str(rid) for rid in redis.smembers(host_key(host))]
        if not run_ids:
            return []
        reports = [_parse_report(raw) for raw in redis.mget([run_key(rid) for rid in run_ids])]
        # A retry on another pod overwrites its run key with the new host while the stable run_id
        # lingers in the old pod's set; without this filter a later death on the old pod would count
        # the retry's workload as a local co-tenant. Membership alone is not evidence — the report
        # itself must claim this host. Stale members age out via the set's TTL.
        found = [report for report in reports if report is not None and report.get("host") == host]
        found.sort(key=lambda report: report.get("ts") or 0, reverse=True)
        return found
    except Exception:
        LOGGER.debug("workload_report_read_failed", host=host, exc_info=True)
        return []


def enrich_death_event_properties(
    properties: dict[str, Any], *, run_id: str, host: str | None, death_ts: float | None = None
) -> None:
    """Fold workload self-reports into a `dwh_pod_heartbeat_timeout` event's properties, in place.

    `self_*` describes the dead attempt's own last report. `co_tenant_*` is **aggregates only** —
    count, max/sum of peaks, phase mix — never identifiers: a pod is multi-tenant, so co-tenant
    reports belong to other teams, and anything persisted here (or later snapshotted onto a
    team-scoped row) must not carry one team's schema/run ids into another team's data. The blame
    question the aggregates must still answer is "was anything on this pod holding more than us",
    which only needs the maximum. Absent reports (rollout, expired keys, Redis down) add nothing —
    the event stays exactly as it was before this existed.

    `death_ts` (the dead run's last heartbeat, same pod clock as the reports) additionally yields
    `co_tenant_correlated_max_peak_buffer_bytes`: the max peak over only the co-tenants whose report
    is time-correlated with the death. The raw max spans keys retained for up to the TTL, so a
    neighbour that crashed an hour ago — or one still running whose report has refreshed since —
    could carry a historical peak into blame for a death it had nothing to do with. A report within
    the correlation bound of the death is either the co-tenant that died alongside us (its sampler
    stopped when we did) or one sampled moments around the death; anything else is history.
    """
    try:
        reports = read_workload_reports(host) if host else []
        own = next((report for report in reports if report.get("run_id") == run_id), None)
        if own is None:
            # A clean earlier attempt may have SREM'd itself from the host set; the run key survives.
            redis = _redis_client()
            own = _parse_report(redis.get(run_key(run_id))) if redis is not None else None
            # Callers without a host (consumer-side deaths) still get co-tenants: the own report
            # remembers which pod it ran on.
            if own is not None and not host and own.get("host"):
                reports = read_workload_reports(str(own["host"]))
        if own is not None:
            properties.update(
                {
                    "self_phase": own.get("phase"),
                    "self_buffer_bytes": own.get("buffer_bytes"),
                    "self_peak_buffer_bytes": own.get("peak_buffer_bytes"),
                    "self_rss_bytes": own.get("rss_bytes"),
                    "self_peak_rss_bytes": own.get("peak_rss_bytes"),
                    "self_report_age_seconds": round(time.time() - own["ts"], 1) if own.get("ts") is not None else None,
                    "self_report_ts": own.get("ts"),
                }
            )
        co_tenants = [report for report in reports if report.get("run_id") != run_id]
        if co_tenants:
            peaks = [int(report.get("peak_buffer_bytes") or 0) for report in co_tenants]
            currents = [int(report.get("buffer_bytes") or 0) for report in co_tenants]
            phases = [str(report.get("phase")) for report in co_tenants]
            properties.update(
                {
                    "co_tenant_report_count": len(co_tenants),
                    "co_tenant_max_peak_buffer_bytes": max(peaks),
                    "co_tenant_sum_buffer_bytes": sum(currents),
                    "co_tenant_merge_count": sum(1 for phase in phases if phase == "merge"),
                    "co_tenant_extract_count": sum(1 for phase in phases if phase == "extract"),
                    "co_tenant_repartition_count": sum(1 for phase in phases if phase == "repartition"),
                }
            )
            if death_ts is not None:
                bound = 2.0 * workload_report_interval_seconds()
                correlated = [
                    int(report.get("peak_buffer_bytes") or 0)
                    for report in co_tenants
                    if report.get("ts") is not None and abs(float(report["ts"]) - death_ts) <= bound
                ]
                if correlated:
                    properties["co_tenant_correlated_max_peak_buffer_bytes"] = max(correlated)
    except Exception:
        LOGGER.debug("workload_report_enrich_failed", run_id=run_id, exc_info=True)
