"""Local triage for backend test timings sourced from Backend CI JUnit artifacts.

Subcommands fetch `junit-results-backend-*` artifacts via `gh run download`
and render ASCII summaries: top-N slowest tests, shard wall-time imbalance,
diffs between two runs, and regressions vs a rolling baseline.

The CI side produces a richer team-wide dashboard via `ctrf-io/github-test-reporter`
in the workflow run summary; this command is the per-developer triage path.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import statistics
import subprocess
from datetime import datetime
from pathlib import Path

import click

from hogli_commands._junit_parser import Shard, collect_shards

REPO = "PostHog/posthog"
WORKFLOW = "ci-backend.yml"
ARTIFACT_PATTERN = "junit-results-backend-*"
# Runs that skip tests via path filtering complete in ~20s; real test runs
# take 15+ minutes. 300s screens out almost all no-op runs.
MIN_RUN_DURATION_SECONDS = 300
CACHE_DIR = Path.home() / ".cache" / "posthog" / "test-timings"


def _gh_json(*args: str) -> list[dict] | dict:
    """Run `gh api` and return parsed JSON. Raises ClickException on failure."""
    try:
        result = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f"gh api failed: {exc.stderr.strip() or exc}") from exc
    except FileNotFoundError as exc:
        raise click.ClickException("`gh` CLI not found on PATH; install GitHub CLI to use this command") from exc
    return json.loads(result.stdout)


def _list_recent_master_runs(limit: int) -> list[dict]:
    """Return up to `limit` recent successful master runs of ci-backend.yml
    that actually executed tests (run duration > MIN_RUN_DURATION_SECONDS)."""
    per_page = max(limit * 4, 20)
    payload = _gh_json(
        f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?status=success&branch=master&per_page={per_page}"
    )
    runs = payload["workflow_runs"] if isinstance(payload, dict) else []
    selected: list[dict] = []
    for run in runs:
        try:
            started = datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
            updated = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if (updated - started).total_seconds() <= MIN_RUN_DURATION_SECONDS:
            continue
        selected.append(run)
        if len(selected) >= limit:
            break
    return selected


def _find_latest_master_run() -> str:
    runs = _list_recent_master_runs(1)
    if not runs:
        raise click.ClickException("no recent successful master Backend CI run found that ran tests")
    return str(runs[0]["id"])


def _download_junit_artifacts(run_id: str, dest: Path) -> Path:
    """Download all `junit-results-backend-*` artifacts for a run into `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [
        "gh",
        "run",
        "download",
        run_id,
        "--repo",
        REPO,
        "--pattern",
        ARTIFACT_PATTERN,
        "--dir",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"`gh run download {run_id}` failed: {exc.stderr.strip() or exc}\n"
            f"Likely cause: artifacts have expired (90 days) or run never produced junit output."
        ) from exc
    return dest


def _cached_durations_path(run_id: str) -> Path:
    return CACHE_DIR / f"{run_id}.json"


def _load_run_durations(run_id: str, *, segment: str | None = None) -> dict[str, float]:
    """Return per-test durations for a run, using the on-disk cache when present.

    Cache contains the segmented map keyed by segment so a later --segment
    filter doesn't force a re-download.
    """
    cache_path = _cached_durations_path(run_id)
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            if isinstance(data, dict) and "segments" in data:
                return _coerce_segment(data, segment)
        except (OSError, json.JSONDecodeError):
            pass

    with tempfile.TemporaryDirectory() as tmp:
        artifacts = _download_junit_artifacts(run_id, Path(tmp))
        shards = collect_shards(artifacts)
    payload = _build_cache_payload(shards)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload))
    return _coerce_segment(payload, segment)


def _build_cache_payload(shards: list[Shard]) -> dict:
    segments: dict[str, dict[str, float]] = {}
    for s in shards:
        seg = segments.setdefault(s.segment, {})
        for t in s.tests:
            if t.outcome == "skipped":
                continue
            prev = seg.get(t.nodeid)
            if prev is None or t.duration > prev:
                seg[t.nodeid] = t.duration
    shard_walls = [
        {
            "label": s.label,
            "segment": s.segment,
            "wall_seconds": s.wall_seconds,
            "testcase_seconds": s.testcase_seconds,
            "overhead_seconds": s.overhead_seconds,
        }
        for s in shards
    ]
    return {"segments": segments, "shards": shard_walls}


def _coerce_segment(payload: dict, segment: str | None) -> dict[str, float]:
    segments = payload.get("segments", {})
    if segment is None:
        merged: dict[str, float] = {}
        for seg_map in segments.values():
            for nodeid, duration in seg_map.items():
                prev = merged.get(nodeid)
                if prev is None or duration > prev:
                    merged[nodeid] = duration
        return merged
    return dict(segments.get(segment, {}))


def _format_seconds(value: float) -> str:
    return f"{value:>7.2f}s"


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return "..." + value[-(width - 3) :]


def _render_top_n(durations: dict[str, float], *, top: int, run_id: str, segment: str | None) -> None:
    items = sorted(durations.items(), key=lambda x: x[1], reverse=True)[:top]
    if not items:
        click.echo("no test data available")
        return
    seg_str = f" [segment={segment}]" if segment else ""
    click.echo(f"\nTop {len(items)} slowest tests for run {run_id}{seg_str}")
    click.echo("-" * 100)
    click.echo(f"{'#':>4}  {'duration':>9}  test")
    click.echo("-" * 100)
    for i, (nodeid, duration) in enumerate(items, 1):
        click.echo(f"{i:>4}  {_format_seconds(duration)}  {_truncate(nodeid, 84)}")
    total = sum(durations.values())
    click.echo("-" * 100)
    click.echo(f"  total testcase time across {len(durations)} tests: {total:.1f}s ({total / 60:.1f} min)")


def _render_shard_imbalance(shards_payload: list[dict], *, segment: str | None) -> None:
    if not shards_payload:
        return
    rows = [s for s in shards_payload if segment is None or s.get("segment") == segment]
    if not rows:
        return
    rows.sort(key=lambda s: s["wall_seconds"], reverse=True)
    walls = [s["wall_seconds"] for s in rows]
    click.echo(f"\nShard wall time ({len(rows)} shards, longest first)")
    click.echo("-" * 80)
    click.echo(f"  {'shard':<20}  {'wall':>10}  {'tests':>10}  {'overhead':>10}")
    click.echo("-" * 80)
    for s in rows:
        click.echo(
            f"  {s['label']:<20}  {_format_seconds(s['wall_seconds'])}  "
            f"{_format_seconds(s['testcase_seconds'])}  {_format_seconds(s['overhead_seconds'])}"
        )
    click.echo("-" * 80)
    if len(walls) >= 2:
        click.echo(
            f"  imbalance: max={max(walls):.1f}s, min={min(walls):.1f}s, "
            f"spread={max(walls) - min(walls):.1f}s, median={statistics.median(walls):.1f}s"
        )


def _render_compare(
    a: dict[str, float],
    b: dict[str, float],
    *,
    top: int,
    run_a: str,
    run_b: str,
    min_delta: float,
) -> None:
    """Show biggest movers from run A to run B. Tests in only one run are listed separately."""
    common = set(a) & set(b)
    deltas = [(nodeid, b[nodeid] - a[nodeid]) for nodeid in common]
    deltas = [d for d in deltas if abs(d[1]) >= min_delta]
    deltas.sort(key=lambda x: x[1], reverse=True)

    regressions = deltas[:top]
    improvements = sorted(deltas, key=lambda x: x[1])[:top]

    click.echo(f"\nCompare run {run_a} -> {run_b}  (min delta: {min_delta:.2f}s)")
    if regressions:
        click.echo("-" * 100)
        click.echo(f"  {'delta':>8}  {'before':>8}  {'after':>8}  test")
        click.echo("-" * 100)
        click.echo(f"Top {len(regressions)} regressions:")
        for nodeid, delta in regressions:
            click.echo(
                f"  {f'+{delta:.2f}s':>8}  {_format_seconds(a[nodeid])}  "
                f"{_format_seconds(b[nodeid])}  {_truncate(nodeid, 64)}"
            )
    else:
        click.echo("  no regressions above threshold")

    if improvements and improvements[0][1] < 0:
        click.echo(f"\nTop {len([d for d in improvements if d[1] < 0])} improvements:")
        for nodeid, delta in improvements:
            if delta >= 0:
                break
            click.echo(
                f"  {f'{delta:.2f}s':>8}  {_format_seconds(a[nodeid])}  "
                f"{_format_seconds(b[nodeid])}  {_truncate(nodeid, 64)}"
            )

    only_a = set(a) - set(b)
    only_b = set(b) - set(a)
    if only_a or only_b:
        click.echo(f"\nTests only in {run_a}: {len(only_a)}    Tests only in {run_b}: {len(only_b)}")


def _render_regressions(
    head: dict[str, float],
    baseline: dict[str, dict[str, float]],
    *,
    head_run_id: str,
    top: int,
    min_delta: float,
    min_factor: float,
) -> None:
    """Compare head against the per-test median across baseline runs."""
    medians: dict[str, float] = {}
    for nodeid in head:
        samples = [
            durations[nodeid] for durations in baseline.values() if nodeid in durations and durations[nodeid] > 0
        ]
        if samples:
            medians[nodeid] = statistics.median(samples)

    flagged: list[tuple[str, float, float, float]] = []
    for nodeid, current in head.items():
        median = medians.get(nodeid)
        if median is None or median <= 0:
            continue
        delta = current - median
        factor = current / median
        if delta >= min_delta and factor >= min_factor:
            flagged.append((nodeid, current, median, factor))
    flagged.sort(key=lambda x: x[1] - x[2], reverse=True)

    click.echo(
        f"\nRegressions in run {head_run_id} vs median of {len(baseline)} prior runs "
        f"(min_delta={min_delta:.2f}s, min_factor={min_factor:.2f}x)"
    )
    if not flagged:
        click.echo("  none")
        return
    rows = flagged[:top]
    click.echo("-" * 100)
    click.echo(f"  {'now':>8}  {'median':>8}  {'factor':>7}  test")
    click.echo("-" * 100)
    for nodeid, current, median, factor in rows:
        click.echo(f"  {_format_seconds(current)}  {_format_seconds(median)}  {factor:>6.2f}x  {_truncate(nodeid, 60)}")


# ---------- click commands ----------


@click.command(name="test-timings:latest", help="Top-N slowest tests from the latest successful master Backend CI run")
@click.option("--top", default=30, show_default=True, help="number of slowest tests to display")
@click.option("--segment", default=None, help="filter to a single segment (e.g. core, temporal, products)")
@click.option("--shards/--no-shards", default=True, show_default=True, help="show per-shard wall-time imbalance")
def latest(top: int, segment: str | None, shards: bool) -> None:
    run_id = _find_latest_master_run()
    click.echo(f"Latest master run: {run_id}")
    _show_run(run_id, top=top, segment=segment, with_shards=shards)


@click.command(name="test-timings:show", help="Top-N slowest tests for a specific Backend CI run")
@click.argument("run_id")
@click.option("--top", default=30, show_default=True, help="number of slowest tests to display")
@click.option("--segment", default=None, help="filter to a single segment (e.g. core, temporal, products)")
@click.option("--shards/--no-shards", default=True, show_default=True, help="show per-shard wall-time imbalance")
def show(run_id: str, top: int, segment: str | None, shards: bool) -> None:
    _show_run(run_id, top=top, segment=segment, with_shards=shards)


def _show_run(run_id: str, *, top: int, segment: str | None, with_shards: bool) -> None:
    durations = _load_run_durations(run_id, segment=segment)
    payload = _read_cache(run_id)
    _render_top_n(durations, top=top, run_id=run_id, segment=segment)
    if with_shards:
        _render_shard_imbalance(payload.get("shards", []), segment=segment)


def _read_cache(run_id: str) -> dict:
    path = _cached_durations_path(run_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@click.command(name="test-timings:compare", help="Compare two Backend CI runs and show biggest test-time movers")
@click.argument("run_a")
@click.argument("run_b")
@click.option("--top", default=20, show_default=True, help="number of biggest movers to display")
@click.option("--min-delta", default=2.0, show_default=True, help="minimum absolute delta in seconds to flag")
@click.option("--segment", default=None, help="filter to a single segment (e.g. core, temporal, products)")
def compare(run_a: str, run_b: str, top: int, min_delta: float, segment: str | None) -> None:
    a = _load_run_durations(run_a, segment=segment)
    b = _load_run_durations(run_b, segment=segment)
    _render_compare(a, b, top=top, run_a=run_a, run_b=run_b, min_delta=min_delta)


@click.command(
    name="test-timings:regressions",
    help="Flag tests in the latest master run that grew vs the median of the last N master runs",
)
@click.option("--baseline", default=10, show_default=True, help="number of prior master runs to use as baseline")
@click.option("--top", default=30, show_default=True, help="number of biggest regressions to display")
@click.option("--min-delta", default=2.0, show_default=True, help="minimum absolute regression in seconds to flag")
@click.option("--min-factor", default=1.5, show_default=True, help="minimum slowdown factor (current / median)")
@click.option("--segment", default=None, help="filter to a single segment (e.g. core, temporal, products)")
def regressions(baseline: int, top: int, min_delta: float, min_factor: float, segment: str | None) -> None:
    runs = _list_recent_master_runs(baseline + 1)
    if len(runs) < 2:
        raise click.ClickException(f"need at least 2 master runs, found {len(runs)}")
    head_run = str(runs[0]["id"])
    history_ids = [str(r["id"]) for r in runs[1 : baseline + 1]]
    click.echo(
        f"Head: master run {head_run}\n"
        f"Baseline: {len(history_ids)} prior master runs (cached after first download in {CACHE_DIR})"
    )
    head = _load_run_durations(head_run, segment=segment)
    history: dict[str, dict[str, float]] = {}
    for rid in history_ids:
        try:
            history[rid] = _load_run_durations(rid, segment=segment)
        except click.ClickException as exc:
            click.echo(f"  warning: {rid}: {exc.message}", err=True)
    _render_regressions(head, history, head_run_id=head_run, top=top, min_delta=min_delta, min_factor=min_factor)


@click.command(name="test-timings:cache:clear", help="Clear the local test-timings cache")
def cache_clear() -> None:
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        click.echo(f"removed {CACHE_DIR}")
    else:
        click.echo(f"{CACHE_DIR} does not exist")
