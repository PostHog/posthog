from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from hogli_commands import test_timings
from hogli_commands._junit_parser import collect_shards, parse_artifact_dir_name, parse_shard, per_test_durations


def _write_junit(artifact_dir: Path, *, filename: str = "junit-core.xml", body: str, time: str = "10.0") -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / filename
    path.write_text(
        textwrap.dedent(
            f"""\
            <?xml version="1.0"?>
            <testsuites>
              <testsuite name="pytest" timestamp="2026-05-04T10:00:00.000000" time="{time}">
                {body}
              </testsuite>
            </testsuites>
            """
        )
    )
    return path


# ---------- _junit_parser ----------


@pytest.mark.parametrize(
    "dir_name,expected",
    [
        ("junit-results-backend-core-29", ("backend", "core", 29)),
        ("junit-results-backend-temporal-3", ("backend", "temporal", 3)),
        ("junit-results-backend-products-with-dashes-7", ("backend", "products-with-dashes", 7)),
        ("junit-results-async-migrations", ("async-migrations", "async-migrations", None)),
    ],
)
def test_parse_artifact_dir_name(dir_name: str, expected: tuple[str, str, int | None]) -> None:
    assert parse_artifact_dir_name(dir_name) == expected


def test_parse_shard_extracts_durations_and_outcomes(tmp_path: Path) -> None:
    artifact = tmp_path / "junit-results-backend-core-7"
    xml_path = _write_junit(
        artifact,
        body="""\
            <testcase classname="pkg.test_a.TestA" name="test_fast" time="0.10"/>
            <testcase classname="pkg.test_a.TestA" name="test_slow" time="2.50"/>
            <testcase classname="pkg.test_a.TestA" name="test_rerun" time="0.20"><rerunFailure message="x"/></testcase>
            <testcase classname="pkg.test_a.TestA" name="test_fail" time="0.10"><failure message="x"/></testcase>
            <testcase classname="pkg.test_a.TestA" name="test_skip" time="0.00"><skipped message="x"/></testcase>
        """,
    )
    shard = parse_shard(xml_path, artifact.name)
    assert shard is not None
    assert shard.suite == "backend"
    assert shard.segment == "core"
    assert shard.group == 7
    assert shard.label == "core-7"
    assert shard.wall_seconds == pytest.approx(10.0)
    assert shard.testcase_seconds == pytest.approx(2.9)
    assert shard.overhead_seconds == pytest.approx(7.1)
    assert [t.name for t in shard.tests] == ["test_fast", "test_slow", "test_rerun", "test_fail", "test_skip"]
    assert shard.tests[2].outcome == "rerun_passed"
    assert shard.tests[2].attempts == 2
    assert shard.tests[3].outcome == "failed"
    assert shard.tests[4].outcome == "skipped"
    assert shard.tests[0].nodeid == "pkg/test_a/TestA::test_fast"


def test_parse_shard_returns_none_for_malformed_xml(tmp_path: Path) -> None:
    artifact = tmp_path / "junit-results-backend-core-1"
    artifact.mkdir()
    (artifact / "junit-core.xml").write_text("<not valid xml")
    assert parse_shard(artifact / "junit-core.xml", artifact.name) is None


def test_collect_shards_walks_artifact_dirs(tmp_path: Path) -> None:
    _write_junit(
        tmp_path / "junit-results-backend-core-1",
        body='<testcase classname="m" name="t" time="1.0"/>',
    )
    _write_junit(
        tmp_path / "junit-results-backend-core-2",
        body='<testcase classname="m" name="u" time="2.0"/>',
    )
    shards = collect_shards(tmp_path)
    assert len(shards) == 2
    assert {s.group for s in shards} == {1, 2}


def test_collect_shards_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    assert collect_shards(tmp_path / "does-not-exist") == []


def test_per_test_durations_drops_skipped_and_takes_max(tmp_path: Path) -> None:
    _write_junit(
        tmp_path / "junit-results-backend-core-1",
        body="""\
            <testcase classname="m.T" name="dup" time="1.0"/>
            <testcase classname="m.T" name="skipped" time="0.0"><skipped/></testcase>
        """,
    )
    _write_junit(
        tmp_path / "junit-results-backend-core-2",
        body='<testcase classname="m.T" name="dup" time="3.5"/>',
    )
    durations = per_test_durations(collect_shards(tmp_path))
    assert "m/T::skipped" not in durations
    assert durations["m/T::dup"] == pytest.approx(3.5)


def test_per_test_durations_segment_filter(tmp_path: Path) -> None:
    _write_junit(
        tmp_path / "junit-results-backend-core-1",
        body='<testcase classname="m.T" name="a" time="1.0"/>',
    )
    _write_junit(
        tmp_path / "junit-results-backend-temporal-1",
        body='<testcase classname="m.T" name="b" time="2.0"/>',
    )
    shards = collect_shards(tmp_path)
    core_only = per_test_durations(shards, segment="core")
    assert set(core_only) == {"m/T::a"}
    temporal_only = per_test_durations(shards, segment="temporal")
    assert set(temporal_only) == {"m/T::b"}


# ---------- cache + render helpers ----------


def test_build_cache_payload_groups_by_segment(tmp_path: Path) -> None:
    _write_junit(
        tmp_path / "junit-results-backend-core-1",
        body='<testcase classname="m" name="a" time="1.0"/>',
        time="5.0",
    )
    _write_junit(
        tmp_path / "junit-results-backend-temporal-1",
        body='<testcase classname="m" name="b" time="2.0"/>',
        time="6.0",
    )
    shards = collect_shards(tmp_path)
    payload = test_timings._build_cache_payload(shards)
    assert set(payload["segments"]) == {"core", "temporal"}
    assert payload["segments"]["core"] == {"m::a": pytest.approx(1.0)}
    assert payload["segments"]["temporal"] == {"m::b": pytest.approx(2.0)}
    assert {s["label"] for s in payload["shards"]} == {"core-1", "temporal-1"}


def test_coerce_segment_merges_when_no_filter() -> None:
    payload = {
        "segments": {
            "core": {"a": 1.0, "shared": 2.0},
            "temporal": {"b": 3.0, "shared": 5.0},
        }
    }
    merged = test_timings._coerce_segment(payload, None)
    assert merged == {"a": 1.0, "shared": 5.0, "b": 3.0}


def test_coerce_segment_returns_only_one_segment() -> None:
    payload = {"segments": {"core": {"a": 1.0}, "temporal": {"b": 2.0}}}
    assert test_timings._coerce_segment(payload, "core") == {"a": 1.0}
    assert test_timings._coerce_segment(payload, "missing") == {}


def test_load_run_durations_uses_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_timings, "CACHE_DIR", tmp_path)
    cached = {"segments": {"core": {"posthog::a": 4.2}}, "shards": []}
    (tmp_path / "12345.json").write_text(json.dumps(cached))

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network fetch should not run when cache is fresh")

    monkeypatch.setattr(test_timings, "_download_junit_artifacts", fail)
    out = test_timings._load_run_durations("12345")
    assert out == {"posthog::a": 4.2}


def test_truncate_keeps_short_strings_and_clips_long_ones() -> None:
    assert test_timings._truncate("short", 20) == "short"
    long = "a/very/long/path/that/exceeds/the/configured/width/test::name"
    out = test_timings._truncate(long, 20)
    assert len(out) == 20
    assert out.startswith("...")


# ---------- regression detection ----------


def test_render_regressions_flags_only_above_thresholds(capsys: pytest.CaptureFixture[str]) -> None:
    head = {
        "stable": 1.0,
        "slow_grew_a_lot": 12.0,
        "slow_grew_below_factor": 4.0,
        "slow_grew_below_delta": 1.5,
        "new_test": 9.0,
    }
    baseline = {
        "run_a": {"stable": 1.0, "slow_grew_a_lot": 4.0, "slow_grew_below_factor": 3.0, "slow_grew_below_delta": 1.0},
        "run_b": {"stable": 1.0, "slow_grew_a_lot": 4.0, "slow_grew_below_factor": 3.0, "slow_grew_below_delta": 1.0},
    }
    test_timings._render_regressions(head, baseline, head_run_id="HEAD", top=10, min_delta=2.0, min_factor=1.5)
    out = capsys.readouterr().out
    assert "slow_grew_a_lot" in out
    assert "slow_grew_below_factor" not in out  # delta 1.0 < min_delta 2.0 and factor 1.33 < 1.5
    assert "slow_grew_below_delta" not in out
    assert "stable" not in out
    assert "new_test" not in out  # no baseline -> no median -> not flagged


def test_render_compare_lists_regressions_and_improvements(capsys: pytest.CaptureFixture[str]) -> None:
    a = {"steady": 1.0, "got_slower": 2.0, "got_faster": 10.0, "below_threshold": 1.0}
    b = {"steady": 1.0, "got_slower": 8.0, "got_faster": 1.0, "below_threshold": 2.0}
    test_timings._render_compare(a, b, top=5, run_a="A", run_b="B", min_delta=2.0)
    out = capsys.readouterr().out
    assert "got_slower" in out
    assert "got_faster" in out
    assert "below_threshold" not in out
    assert "steady" not in out
