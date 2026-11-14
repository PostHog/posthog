import random

import pytest

from bench import AbRound, AbRow, RouteDelta, RouteStats, RunResult, compare, summarize, summarize_ab


def _route(name: str, p50_ms: float | None, p95_ms: float | None) -> RouteStats:
    return RouteStats(name=name, count=10, errors=0, p50_ms=p50_ms, p95_ms=p95_ms, p99_ms=None, mean_ms=None)


def _run(*routes: RouteStats) -> RunResult:
    return RunResult(
        label="",
        mode="latency",
        base_url="",
        started_at="",
        concurrency=1,
        measured_seconds=1.0,
        throughput_rps=1.0,
        routes=list(routes),
    )


@pytest.mark.parametrize(
    "samples_ms, expected",
    [
        (
            random.Random(7).sample([float(n) for n in range(1, 101)], 100),
            RouteStats(name="r", count=100, errors=2, p50_ms=50.5, p95_ms=95.05, p99_ms=99.01, mean_ms=50.5),
        ),
        (
            [12.0],
            RouteStats(name="r", count=1, errors=2, p50_ms=12.0, p95_ms=12.0, p99_ms=12.0, mean_ms=12.0),
        ),
        (
            [],
            RouteStats(name="r", count=0, errors=2, p50_ms=None, p95_ms=None, p99_ms=None, mean_ms=None),
        ),
    ],
)
def test_summarize_reports_percentiles_of_unsorted_samples(samples_ms: list[float], expected: RouteStats) -> None:
    assert summarize("r", samples_ms, errors=2) == expected


def test_compare_reports_changes_against_base_and_keeps_routes_missing_on_either_side() -> None:
    base = _run(_route("a", 10.0, 20.0), _route("b", 5.0, 9.0), _route("zero", 0.0, 0.0))
    head = _run(_route("zero", 1.0, 1.0), _route("a", 8.0, 30.0), _route("c", 4.0, 6.0))

    assert compare(base, head) == [
        RouteDelta(
            name="a",
            base_p50_ms=10.0,
            head_p50_ms=8.0,
            p50_change_pct=-20.0,
            base_p95_ms=20.0,
            head_p95_ms=30.0,
            p95_change_pct=50.0,
        ),
        RouteDelta(
            name="b",
            base_p50_ms=5.0,
            head_p50_ms=None,
            p50_change_pct=None,
            base_p95_ms=9.0,
            head_p95_ms=None,
            p95_change_pct=None,
        ),
        RouteDelta(
            name="zero",
            base_p50_ms=0.0,
            head_p50_ms=1.0,
            p50_change_pct=None,
            base_p95_ms=0.0,
            head_p95_ms=1.0,
            p95_change_pct=None,
        ),
        RouteDelta(
            name="c",
            base_p50_ms=None,
            head_p50_ms=4.0,
            p50_change_pct=None,
            base_p95_ms=None,
            head_p95_ms=6.0,
            p95_change_pct=None,
        ),
    ]


def test_summarize_ab_pairs_rounds_and_takes_the_median_of_each_side() -> None:
    rounds = [
        AbRound(base=_run(_route("a", 10.0, None), _route("b", 5.0, None)), head=_run(_route("a", 9.0, None))),
        AbRound(base=_run(_route("a", 12.0, None), _route("b", 6.0, None)), head=_run(_route("a", 9.0, None))),
        AbRound(base=_run(_route("a", 11.0, None), _route("b", 7.0, None)), head=_run(_route("a", 10.0, None))),
    ]

    assert summarize_ab(rounds) == [
        AbRow(
            name="a",
            base_p50_ms=11.0,
            head_p50_ms=9.0,
            change_pct=-18.2,
            round_changes_pct=(-10.0, -25.0, -9.1),
        ),
        AbRow(
            name="b",
            base_p50_ms=6.0,
            head_p50_ms=None,
            change_pct=None,
            round_changes_pct=(None, None, None),
        ),
    ]
