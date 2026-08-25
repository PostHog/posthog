import json
import time

import pytest
from unittest import mock

from django.test import override_settings

from products.warehouse_sources.backend.temporal.data_imports import workload_report
from products.warehouse_sources.backend.temporal.data_imports.workload_report import (
    WorkloadReporter,
    enrich_death_event_properties,
    host_key,
    report_buffer_bytes,
    report_phase,
    run_key,
    workload_reporting,
)


def _seed_report(redis, *, run_id: str, host: str, schema_id: str, phase: str, peak: int, ts: float = 100.0) -> None:
    redis.setex(
        run_key(run_id),
        60,
        json.dumps(
            {
                "run_id": run_id,
                "schema_id": schema_id,
                "host": host,
                "phase": phase,
                "buffer_bytes": peak // 2,
                "peak_buffer_bytes": peak,
                "rss_bytes": None,
                "peak_rss_bytes": None,
                "ts": ts,
            }
        ),
    )
    redis.sadd(host_key(host), run_id)


class TestWorkloadReporting:
    def test_samples_round_trip_through_redis_with_hook_values_and_peaks(self):
        # Writer and reader live on different pods at different times: the sample written before a
        # death is what the retry reads back. A drifted key or field name would silently null every
        # death enrichment, which is the whole point of this module.
        redis = workload_report._redis_client()
        assert redis is not None
        with workload_reporting(team_id=1, schema_id="s1", run_id="run-rt", host="pod-rt"):
            report_phase("merge")
            report_buffer_bytes(500)
            report_buffer_bytes(200)  # current drops, peak must not
            reporter = workload_report._current_reporter.get()
            assert reporter is not None
            reporter._write_sample(redis)

            raw = redis.get(run_key("run-rt"))
            assert raw is not None
            sample = json.loads(raw)
            assert sample["phase"] == "merge"
            assert sample["buffer_bytes"] == 200
            assert sample["peak_buffer_bytes"] == 500
            assert redis.sismember(host_key("pod-rt"), "run-rt")

        # Clean completion: dropped from the running set (it is no longer a live co-tenant), but the
        # final sample survives for a death that happens moments later on the same pod.
        assert not redis.sismember(host_key("pod-rt"), "run-rt")
        final = json.loads(redis.get(run_key("run-rt")))
        assert final["phase"] == "finished"
        # A stale current buffer here inflates `co_tenant_sum_buffer_bytes` for a neighbour that
        # dies afterwards; the peak stays because that is what blame is judged on.
        assert final["buffer_bytes"] == 0
        assert final["peak_buffer_bytes"] == 500

    def test_enrichment_attaches_own_report_and_aggregates_co_tenants_without_identifiers(self):
        # A pod is multi-tenant, so co-tenant reports belong to other teams: the event may carry only
        # aggregates (the max answers "was anything bigger than us"), never their schema or run ids.
        # Leaking an identifier here would put one team's schema ids in another team's failure record.
        redis = workload_report._redis_client()
        _seed_report(redis, run_id="run-dead", host="pod-a", schema_id="s-dead", phase="extract", peak=900)
        _seed_report(redis, run_id="run-big", host="pod-a", schema_id="s-big", phase="merge", peak=5000)
        _seed_report(redis, run_id="run-small", host="pod-a", schema_id="s-small", phase="extract", peak=10)

        properties: dict = {}
        enrich_death_event_properties(properties, run_id="run-dead", host="pod-a")

        assert properties["self_phase"] == "extract"
        assert properties["self_peak_buffer_bytes"] == 900
        assert properties["co_tenant_report_count"] == 2
        assert properties["co_tenant_max_peak_buffer_bytes"] == 5000
        assert properties["co_tenant_merge_count"] == 1
        assert properties["co_tenant_extract_count"] == 1
        serialized = json.dumps(properties)
        assert "s-big" not in serialized and "s-small" not in serialized and "run-big" not in serialized

    def test_enrichment_correlated_max_ignores_peaks_not_near_the_death(self):
        # Run keys live for hours and peaks are lifetime-high-water marks, so the raw co-tenant max
        # can carry a neighbour's crash from an hour ago (or a long-released peak on a refreshed
        # report) into blame for a death it had nothing to do with. The correlated max — what the
        # durable row snapshots for the culprit rule — may only include reports sampled around the
        # death itself.
        redis = workload_report._redis_client()
        death_ts = 10_000.0
        _seed_report(redis, run_id="run-dead2", host="pod-b", schema_id="s-dead", phase="merge", peak=900, ts=death_ts)
        # Died alongside us: last sample one interval before the shared death.
        _seed_report(
            redis, run_id="run-with", host="pod-b", schema_id="s-w", phase="merge", peak=5000, ts=death_ts - 25
        )
        # Crashed an hour earlier; its key and huge peak linger until the TTL.
        _seed_report(
            redis, run_id="run-old", host="pod-b", schema_id="s-o", phase="merge", peak=9_000_000, ts=death_ts - 3600
        )
        # Survivor still sampling minutes after the death: its lifetime peak is not evidence either.
        _seed_report(
            redis, run_id="run-later", host="pod-b", schema_id="s-l", phase="merge", peak=7000, ts=death_ts + 300
        )

        properties: dict = {}
        enrich_death_event_properties(properties, run_id="run-dead2", host="pod-b", death_ts=death_ts)

        assert properties["co_tenant_max_peak_buffer_bytes"] == 9_000_000  # raw telemetry keeps history
        assert properties["co_tenant_correlated_max_peak_buffer_bytes"] == 5000

    def test_enrichment_is_silent_when_no_reports_exist(self):
        # Rollout reality: workers without the reporter (old deploys, disabled fleet) must produce
        # byte-identical events to today, or every dashboard on this event breaks during rollout.
        properties = {"host": "pod-none"}
        enrich_death_event_properties(properties, run_id="run-none", host="pod-none")
        assert properties == {"host": "pod-none"}

    @override_settings(DATA_WAREHOUSE_WORKLOAD_REPORT_INTERVAL_SECONDS=0)
    def test_interval_zero_is_a_full_kill_switch(self):
        # The fleet off-switch has to mean off: no thread, hooks are no-ops, and the teardown emits
        # neither a Redis sample nor a watermark event — otherwise "disabled" still writes telemetry.
        redis = workload_report._redis_client()
        with mock.patch("posthoganalytics.capture") as capture:
            with workload_reporting(team_id=1, schema_id="s1", run_id="run-off", host="pod-off"):
                reporter = workload_report._current_reporter.get()
                assert reporter is not None and reporter._thread is None
                report_phase("merge")
                report_buffer_bytes(999_999_999_999)
        assert redis is not None and redis.get(run_key("run-off")) is None
        capture.assert_not_called()

    def test_zombie_attempt_stands_down_when_a_newer_attempt_owns_the_run_key(self):
        # Retries share the run_id, and a heartbeat-timed-out attempt keeps running as a zombie while
        # its retry reports under the same key. Without the attempt guard the zombie's sampler keeps
        # clobbering the live attempt's report, and its eventual stop() overwrites the key with
        # "finished" and SREMs the live attempt from the host set — corrupting both the next death's
        # own-report and the pod's co-tenant list.
        redis = workload_report._redis_client()
        assert redis is not None
        zombie = WorkloadReporter(team_id=1, schema_id="s1", run_id="run-z", host="pod-z", attempt=1)
        zombie._enabled = True  # a started reporter, minus the sampler thread
        zombie.set_buffer_bytes(111)
        zombie._write_sample(redis)  # attempt 1 owns the key while no retry exists

        retry = WorkloadReporter(team_id=1, schema_id="s1", run_id="run-z", host="pod-z", attempt=2)
        retry._enabled = True
        retry.set_buffer_bytes(222)
        retry._write_sample(redis)  # the newer attempt takes the key over

        zombie.set_buffer_bytes(999)
        zombie._write_sample(redis)
        assert zombie._superseded and zombie._stop_event.is_set()
        zombie.stop()

        sample = json.loads(redis.get(run_key("run-z")))
        assert sample["attempt"] == 2 and sample["peak_buffer_bytes"] == 222 and sample["phase"] != "finished"
        assert redis.sismember(host_key("pod-z"), "run-z"), "zombie stop() must not SREM the live attempt"

    def test_stale_host_set_member_from_a_retried_run_is_excluded(self):
        # An attempt dies on pod A, its retry runs on pod B and overwrites the run key with B's
        # report while the stable run_id lingers in A's set. Counting it as an A co-tenant would
        # attribute B's workload to a death on A. Membership is not evidence; the report must claim
        # the host it is read for.
        redis = workload_report._redis_client()
        assert redis is not None
        _seed_report(redis, run_id="run-moved", host="pod-stale-b", schema_id="s-moved", phase="merge", peak=5000)
        redis.sadd(host_key("pod-stale-a"), "run-moved")  # stale membership from the dead first attempt
        _seed_report(redis, run_id="run-local", host="pod-stale-a", schema_id="s-local", phase="merge", peak=10)

        reports = workload_report.read_workload_reports("pod-stale-a")
        assert [report["run_id"] for report in reports] == ["run-local"]

    def test_batcher_flips_phase_back_to_extract_after_a_merge(self):
        # v2 interleaves extract and merge per chunk. Without the batcher re-declaring "extract" on
        # each materialization, the writer's "merge" latches after the first chunk and every later
        # mid-extract death reads as a merge death — biasing the phase distribution this telemetry
        # exists to measure.
        import pyarrow as pa
        import structlog

        from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher

        with workload_reporting(team_id=1, schema_id="s1", run_id="run-phase", host="pod-ph"):
            reporter = workload_report._current_reporter.get()
            assert reporter is not None
            report_phase("merge")
            batcher = Batcher(logger=structlog.get_logger())
            batcher.batch(pa.table({"id": pa.array([1, 2, 3])}))
            assert reporter._phase == "extract"

    def test_hooks_outside_a_reporting_context_are_no_ops(self):
        # Code paths shared with processes that opted out of reporting must never raise or write when
        # the hooks fire with no reporter bound.
        report_phase("merge")
        report_buffer_bytes(42)

    @override_settings(DATA_WAREHOUSE_WORKLOAD_HIGH_WATERMARK_BYTES=1000)
    def test_high_watermark_event_fires_only_above_threshold(self):
        # The watermark event is the only durable record of surviving runs' tails; firing on every run
        # would flood the event stream, and never firing would leave classification thresholds
        # calibrated on deaths alone.
        # The analytics import is deferred inside the capture helper, so patch the global module.
        with mock.patch("posthoganalytics.capture") as capture:
            with workload_reporting(team_id=1, schema_id="s1", run_id="run-low", host="pod-w"):
                report_buffer_bytes(999)
            capture.assert_not_called()

            with workload_reporting(team_id=1, schema_id="s1", run_id="run-high", host="pod-w"):
                report_buffer_bytes(5000)
            capture.assert_called_once()
            properties = capture.call_args.kwargs["properties"]
            assert properties["peak_buffer_bytes"] == 5000
            assert properties["run_id"] == "run-high"
            assert properties["outcome"] == "completed"

            # A run that raises still emits (its peak is a real observation) but must be labeled, or
            # failed runs contaminate the survivors-only distribution the thresholds come from.
            capture.reset_mock()
            with pytest.raises(RuntimeError):
                with workload_reporting(team_id=1, schema_id="s1", run_id="run-boom", host="pod-w"):
                    report_buffer_bytes(7000)
                    raise RuntimeError("merge failed")
            assert capture.call_args.kwargs["properties"]["outcome"] == "raised"


class TestWorkloadReporterThread:
    def test_start_and_stop_lifecycle_writes_final_sample(self):
        # The thread is the production write path; a lifecycle regression (never starts, never joins)
        # would silently stop all sampling fleet-wide.
        reporter = WorkloadReporter(team_id=1, schema_id="s1", run_id="run-thread", host="pod-thread")
        with override_settings(DATA_WAREHOUSE_WORKLOAD_REPORT_INTERVAL_SECONDS=3600):
            reporter.start()
        assert reporter._thread is not None and reporter._thread.is_alive()

        # The first sample must land immediately, not after the first interval: the fastest OOMs die
        # inside that window and never reach stop(), so waiting would blind us to exactly them.
        redis = workload_report._redis_client()
        assert redis is not None
        deadline = time.monotonic() + 5
        while redis.get(run_key("run-thread")) is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert redis.get(run_key("run-thread")) is not None, "no immediate first sample"

        reporter.set_buffer_bytes(777)
        reporter.stop()
        assert not reporter._thread.is_alive()

        redis = workload_report._redis_client()
        assert redis is not None
        sample = json.loads(redis.get(run_key("run-thread")))
        assert sample["peak_buffer_bytes"] == 777
        assert sample["phase"] == "finished"
