import sys
import json
import time
import random
import asyncio
import argparse
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from http.cookiejar import CookieJar, DefaultCookiePolicy
from pathlib import Path
from typing import Any, Literal

import httpx

SCENARIO_PATH = Path(__file__).with_name("scenario.json")
SESSION_COOKIE_NAME = "sessionid"
DEV_API_KEY = "phx_dev_local_test_api_key_1234567890abcdef"
DEV_USER_EMAIL = "test@posthog.com"
DEV_USER_PASSWORD = "12345678"
REQUEST_TIMEOUT_SECONDS = 60.0
QUANTILE_CUTS = 100

Auth = Literal["session", "api_key", "none"]
Mode = Literal["latency", "load"]


@dataclass(frozen=True, kw_only=True, slots=True)
class Route:
    name: str
    method: str
    path: str
    auth: Auth
    weight: int
    body: dict[str, Any] | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class Credentials:
    session_cookie: str | None = field(default=None, repr=False)
    api_key: str | None = field(default=None, repr=False)

    def headers_for(self, auth: Auth) -> dict[str, str] | None:
        if auth == "none":
            return {}
        if auth == "session" and self.session_cookie:
            return {"Cookie": f"{SESSION_COOKIE_NAME}={self.session_cookie}"}
        if auth == "api_key" and self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return None


@dataclass(frozen=True, kw_only=True, slots=True)
class PreparedRequest:
    name: str
    method: str
    url: str
    weight: int
    headers: dict[str, str] = field(repr=False)
    body: dict[str, Any] | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class RouteStats:
    name: str
    count: int
    errors: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    mean_ms: float | None


@dataclass(frozen=True, kw_only=True, slots=True)
class RunResult:
    label: str
    mode: Mode
    base_url: str
    started_at: str
    concurrency: int
    measured_seconds: float
    throughput_rps: float
    routes: list[RouteStats]

    @classmethod
    def load(cls, path: Path) -> "RunResult":
        raw = json.loads(path.read_text())
        return cls(**{**raw, "routes": [RouteStats(**route) for route in raw["routes"]]})


@dataclass(frozen=True, kw_only=True, slots=True)
class AbRound:
    base: RunResult
    head: RunResult


@dataclass(frozen=True, kw_only=True, slots=True)
class AbRow:
    name: str
    base_p50_ms: float | None
    head_p50_ms: float | None
    change_pct: float | None
    round_changes_pct: tuple[float | None, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class RouteDelta:
    name: str
    base_p50_ms: float | None
    head_p50_ms: float | None
    p50_change_pct: float | None
    base_p95_ms: float | None
    head_p95_ms: float | None
    p95_change_pct: float | None


def _percentile(cuts: list[float], percentile: int) -> float:
    return round(cuts[percentile - 1], 2)


def summarize(name: str, samples_ms: list[float], errors: int) -> RouteStats:
    if not samples_ms:
        return RouteStats(name=name, count=0, errors=errors, p50_ms=None, p95_ms=None, p99_ms=None, mean_ms=None)
    cuts = statistics.quantiles(samples_ms, n=QUANTILE_CUTS, method="inclusive")
    return RouteStats(
        name=name,
        count=len(samples_ms),
        errors=errors,
        p50_ms=_percentile(cuts, 50),
        p95_ms=_percentile(cuts, 95),
        p99_ms=_percentile(cuts, 99),
        mean_ms=round(statistics.fmean(samples_ms), 2),
    )


def _change_pct(base: float | None, head: float | None) -> float | None:
    if base is None or head is None or base == 0:
        return None
    return round((head - base) / base * 100, 1)


def compare(base: RunResult, head: RunResult) -> list[RouteDelta]:
    base_routes = {route.name: route for route in base.routes}
    head_routes = {route.name: route for route in head.routes}
    names = [*base_routes, *(name for name in head_routes if name not in base_routes)]
    deltas: list[RouteDelta] = []
    for name in names:
        base_route, head_route = base_routes.get(name), head_routes.get(name)
        base_p50 = base_route.p50_ms if base_route else None
        head_p50 = head_route.p50_ms if head_route else None
        base_p95 = base_route.p95_ms if base_route else None
        head_p95 = head_route.p95_ms if head_route else None
        deltas.append(
            RouteDelta(
                name=name,
                base_p50_ms=base_p50,
                head_p50_ms=head_p50,
                p50_change_pct=_change_pct(base_p50, head_p50),
                base_p95_ms=base_p95,
                head_p95_ms=head_p95,
                p95_change_pct=_change_pct(base_p95, head_p95),
            )
        )
    return deltas


def _cell(value: float | None, suffix: str = "") -> str:
    return "—" if value is None else f"{value:g}{suffix}"


def format_run(result: RunResult) -> str:
    lines = [
        f"{result.label or 'run'} · {result.mode} · concurrency {result.concurrency} · {result.throughput_rps:g} rps",
        "",
        "| Route | Requests | Errors | p50 ms | p95 ms | p99 ms | Mean ms |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {r.name} | {r.count} | {r.errors} | {_cell(r.p50_ms)} | {_cell(r.p95_ms)} | {_cell(r.p99_ms)} | {_cell(r.mean_ms)} |"
        for r in result.routes
    ]
    return "\n".join(lines)


def format_comparison(base: RunResult, head: RunResult, deltas: list[RouteDelta]) -> str:
    lines = [
        f"{base.label or 'base'} → {head.label or 'head'} · {head.mode}",
        "",
        "| Route | p50 base | p50 head | p50 change | p95 base | p95 head | p95 change |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {d.name} | {_cell(d.base_p50_ms)} | {_cell(d.head_p50_ms)} | {_cell(d.p50_change_pct, '%')} "
        f"| {_cell(d.base_p95_ms)} | {_cell(d.head_p95_ms)} | {_cell(d.p95_change_pct, '%')} |"
        for d in deltas
    ]
    return "\n".join(lines)


def _p50(result: RunResult, name: str) -> float | None:
    return next((route.p50_ms for route in result.routes if route.name == name), None)


def _median(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(statistics.median(present), 2) if present else None


def summarize_ab(rounds: list[AbRound]) -> list[AbRow]:
    names = dict.fromkeys(route.name for ab_round in rounds for route in [*ab_round.base.routes, *ab_round.head.routes])
    rows: list[AbRow] = []
    for name in names:
        base_p50s = [_p50(ab_round.base, name) for ab_round in rounds]
        head_p50s = [_p50(ab_round.head, name) for ab_round in rounds]
        base_median, head_median = _median(base_p50s), _median(head_p50s)
        rows.append(
            AbRow(
                name=name,
                base_p50_ms=base_median,
                head_p50_ms=head_median,
                change_pct=_change_pct(base_median, head_median),
                round_changes_pct=tuple(_change_pct(base, head) for base, head in zip(base_p50s, head_p50s)),
            )
        )
    return rows


def format_ab(rows: list[AbRow], rounds: int) -> str:
    lines = [
        f"p50 medians over {rounds} concurrent rounds",
        "",
        "| Route | p50 base | p50 head | change | change per round |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {row.name} | {_cell(row.base_p50_ms)} | {_cell(row.head_p50_ms)} | {_cell(row.change_pct, '%')} "
        f"| {', '.join(_cell(change, '%') for change in row.round_changes_pct)} |"
        for row in rows
    ]
    return "\n".join(lines)


def _cookieless_client(base_url: str, concurrency: int) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
        cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])),
    )


async def log_in(base_url: str, email: str, password: str) -> str:
    async with httpx.AsyncClient(base_url=base_url, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post("/api/login/", json={"email": email, "password": password})
        response.raise_for_status()
        session_cookie = client.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        raise SystemExit("Login returned no session cookie. Pass --session-cookie instead.")
    return session_cookie


async def discover_variables(client: httpx.AsyncClient, credentials: Credentials) -> dict[str, str]:
    headers = credentials.headers_for("session") or credentials.headers_for("api_key") or {}
    me = await client.get("/api/users/@me/", headers=headers)
    me.raise_for_status()
    team = me.json()["team"]
    variables = {"project_id": str(team["project_id"]), "project_token": team["api_token"]}
    dashboards = await client.get(f"/api/projects/{variables['project_id']}/dashboards/?limit=1", headers=headers)
    dashboards.raise_for_status()
    if results := dashboards.json()["results"]:
        variables["dashboard_id"] = str(results[0]["id"])
    return variables


def load_scenario(path: Path) -> list[Route]:
    return [Route(**route) for route in json.loads(path.read_text())]


def parse_variables(pairs: list[str]) -> dict[str, str]:
    return {key: value for key, _, value in (pair.partition("=") for pair in pairs)}


def prepare(routes: list[Route], credentials: Credentials, variables: dict[str, str]) -> list[PreparedRequest]:
    prepared: list[PreparedRequest] = []
    for route in routes:
        headers = credentials.headers_for(route.auth)
        if headers is None:
            sys.stderr.write(f"skip {route.name}: no {route.auth} credentials\n")
            continue
        try:
            url = route.path.format_map(variables)
        except KeyError as missing:
            sys.stderr.write(f"skip {route.name}: no value for {missing}\n")
            continue
        prepared.append(
            PreparedRequest(
                name=route.name, method=route.method, url=url, weight=route.weight, headers=headers, body=route.body
            )
        )
    return prepared


async def _send(client: httpx.AsyncClient, request: PreparedRequest) -> tuple[float, bool]:
    started = time.perf_counter()
    try:
        response = await client.request(request.method, request.url, headers=request.headers, json=request.body)
        succeeded = response.is_success
    except httpx.HTTPError:
        succeeded = False
    return (time.perf_counter() - started) * 1000, succeeded


async def run_latency(
    client: httpx.AsyncClient, requests: list[PreparedRequest], count: int, warmup: int
) -> tuple[list[RouteStats], float]:
    samples_ms: dict[str, list[float]] = {request.name: [] for request in requests}
    errors = dict.fromkeys(samples_ms, 0)
    for _ in range(warmup):
        for request in requests:
            await _send(client, request)
    started = time.perf_counter()
    for _ in range(count):
        for request in requests:
            elapsed_ms, succeeded = await _send(client, request)
            if succeeded:
                samples_ms[request.name].append(elapsed_ms)
            else:
                errors[request.name] += 1
    measured_seconds = time.perf_counter() - started
    return [summarize(name, samples_ms[name], errors[name]) for name in samples_ms], measured_seconds


async def run_load(
    client: httpx.AsyncClient,
    requests: list[PreparedRequest],
    concurrency: int,
    duration_seconds: float,
    warmup_seconds: float,
    seed: int,
) -> tuple[list[RouteStats], float]:
    rng = random.Random(seed)
    weights = [request.weight for request in requests]
    samples_ms: dict[str, list[float]] = {request.name: [] for request in requests}
    errors = dict.fromkeys(samples_ms, 0)
    measure_from = time.perf_counter() + warmup_seconds
    stop_at = measure_from + duration_seconds

    async def worker() -> None:
        while (started := time.perf_counter()) < stop_at:
            request = rng.choices(requests, weights=weights)[0]
            elapsed_ms, succeeded = await _send(client, request)
            if started < measure_from:
                continue
            if succeeded:
                samples_ms[request.name].append(elapsed_ms)
            else:
                errors[request.name] += 1

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return [summarize(name, samples_ms[name], errors[name]) for name in samples_ms], duration_seconds


async def measure(args: argparse.Namespace, base_url: str, label: str) -> RunResult:
    session_cookie = args.session_cookie or await log_in(base_url, args.email, args.password)
    credentials = Credentials(session_cookie=session_cookie, api_key=args.api_key)
    concurrency = args.concurrency if args.mode == "load" else 1
    async with _cookieless_client(base_url, concurrency) as client:
        variables = {**await discover_variables(client, credentials), **parse_variables(args.var)}
        routes = [route for route in load_scenario(args.scenario) if not args.only or route.name in args.only]
        requests = prepare(routes, credentials, variables)
        started_at = datetime.now(UTC).isoformat()
        if args.mode == "latency":
            stats, measured_seconds = await run_latency(client, requests, args.requests, args.warmup_requests)
        else:
            stats, measured_seconds = await run_load(
                client, requests, concurrency, args.duration, args.warmup_seconds, args.seed
            )
    total = sum(route.count for route in stats)
    return RunResult(
        label=label,
        mode=args.mode,
        base_url=base_url,
        started_at=started_at,
        concurrency=concurrency,
        measured_seconds=round(measured_seconds, 2),
        throughput_rps=round(total / measured_seconds, 1) if measured_seconds else 0.0,
        routes=stats,
    )


async def run_ab(args: argparse.Namespace) -> list[AbRound]:
    rounds: list[AbRound] = []
    for index in range(1, args.rounds + 1):
        base, head = await asyncio.gather(
            measure(args, args.base_url, f"base-{index}"), measure(args, args.head_url, f"head-{index}")
        )
        rounds.append(AbRound(base=base, head=head))
    return rounds


def _measure_options() -> argparse.ArgumentParser:
    options = argparse.ArgumentParser(add_help=False)
    options.add_argument("--mode", choices=["latency", "load"], default="latency")
    options.add_argument("--requests", type=int, default=200, help="latency mode: timed requests per route")
    options.add_argument("--warmup-requests", type=int, default=20, help="latency mode: untimed requests per route")
    options.add_argument("--concurrency", type=int, default=8, help="load mode: concurrent clients")
    options.add_argument("--duration", type=float, default=60.0, help="load mode: measured seconds")
    options.add_argument("--warmup-seconds", type=float, default=10.0, help="load mode: untimed seconds")
    options.add_argument("--seed", type=int, default=0, help="load mode: route-mix seed")
    options.add_argument("--scenario", type=Path, default=SCENARIO_PATH)
    options.add_argument("--only", action="append", default=[], help="route name to run; repeatable")
    options.add_argument("--var", action="append", default=[], help="KEY=VALUE path variable; repeatable")
    options.add_argument("--session-cookie", help="skip the login and use this session cookie")
    options.add_argument("--email", default=DEV_USER_EMAIL)
    options.add_argument("--password", default=DEV_USER_PASSWORD)
    options.add_argument("--api-key", default=DEV_API_KEY)
    options.add_argument("--out", type=Path, help="write the JSON result here")
    return options


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stress-test the PostHog API and compare runs.")
    commands = parser.add_subparsers(dest="command", required=True)
    measure_options = _measure_options()

    run_parser = commands.add_parser(
        "run", parents=[measure_options], help="Measure every scenario route and write a JSON result."
    )
    run_parser.add_argument("--base-url", default="http://localhost:8000")
    run_parser.add_argument("--label", default="", help="name for this run, e.g. master@abc1234")

    ab_parser = commands.add_parser(
        "ab",
        parents=[measure_options],
        help="Measure two running servers at the same time, so machine load affects both equally.",
    )
    ab_parser.add_argument("--base-url", required=True)
    ab_parser.add_argument("--head-url", required=True)
    ab_parser.add_argument("--rounds", type=int, default=3)

    compare_parser = commands.add_parser("compare", help="Print per-route deltas between two JSON results.")
    compare_parser.add_argument("base", type=Path)
    compare_parser.add_argument("head", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "compare":
        base, head = RunResult.load(args.base), RunResult.load(args.head)
        sys.stdout.write(format_comparison(base, head, compare(base, head)) + "\n")
        return
    if args.command == "ab":
        rounds = asyncio.run(run_ab(args))
        rows = summarize_ab(rounds)
        if args.out:
            report = {"rounds": [asdict(ab_round) for ab_round in rounds], "summary": [asdict(row) for row in rows]}
            args.out.write_text(json.dumps(report, indent=2))
        sys.stdout.write(format_ab(rows, len(rounds)) + "\n")
        return
    result = asyncio.run(measure(args, args.base_url, args.label))
    if args.out:
        args.out.write_text(json.dumps(asdict(result), indent=2))
    sys.stdout.write(format_run(result) + "\n")
    if failed := [route.name for route in result.routes if route.errors]:
        sys.stderr.write(f"\nRoutes with errors: {', '.join(failed)}\n")


if __name__ == "__main__":
    main()
