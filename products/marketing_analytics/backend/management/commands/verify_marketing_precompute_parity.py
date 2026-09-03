"""Compare the marketing-analytics precompute read path against the live path, per team, for the
aggregated totals — the faithful "does precompute return the same numbers as live" check.

This is the gate before flipping `marketing-analytics-precomputation` on for a team: run it against a
cohort, confirm the precomputed totals match the live events-scan totals within tolerance, then enable
the read flag knowing the served numbers won't move.

Why a command and not raw ClickHouse SQL: the precompute read selects which preagg `job_id`s to merge
(Postgres job tracking) then merges aggregate states across them. Reading the preagg tables directly
would re-implement that job selection and risk diverging from it. Running the actual runner both ways
exercises the real read path, so the comparison reflects what users would see.

Each team is warmed inline as it's checked (the precompute read runs under the CACHE_WARMUP tag, which
routes its ensures to the build path), so a cohort can be validated without deploying the warmer first.

    python manage.py verify_marketing_precompute_parity --teams 2
    python manage.py verify_marketing_precompute_parity --teams-file cohort.txt --date-from -8d --date-to -1d
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.query_tagging import Feature, tags_context
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team


def _aggregated_query(*, date_from: str, date_to: str) -> dict[str, Any]:
    return {
        "kind": "MarketingAnalyticsAggregatedQuery",
        "dateRange": {"date_from": date_from, "date_to": date_to},
        "properties": [],
    }


def _results_to_dict(results: Any) -> dict[str, float]:
    # The aggregated response is a {metric_name: MarketingAnalyticsItem} map; keep the numeric metrics.
    items = results.values() if isinstance(results, dict) else results
    out: dict[str, float] = {}
    for item in items:
        value = getattr(item, "value", None)
        key = getattr(item, "key", None)
        if key is not None and isinstance(value, int | float):
            out[str(key)] = float(value)
    return out


def _pct_diff(precompute_value: float, live_value: float) -> float:
    if live_value == 0:
        return 0.0 if precompute_value == 0 else 100.0
    return abs(precompute_value - live_value) / live_value * 100


def _run(team: Team, query: dict[str, Any], *, use_precompute: bool) -> tuple[dict[str, float], bool]:
    """Run one path. Returns (metrics, served_from_precompute). `served_from_precompute` is only true when
    the read actually read the preagg tables — `dataComputedAt` is set only then, so if it is None the
    precompute path fell back to live (non-precomputable goal or build error) and the comparison would be
    vacuous (live vs live), which the caller flags rather than reporting a hollow OK."""
    runner = get_query_runner(query=query, team=team)
    # Force the path under test regardless of the team's flag: the precompute read warms inline under the
    # CACHE_WARMUP tag (its ensures build), the live read scans events.
    runner.config.conversion_goal_precomputation_enabled = use_precompute  # type: ignore[attr-defined]
    if use_precompute:
        with tags_context(feature=Feature.CACHE_WARMUP):
            response = runner.calculate()
    else:
        response = runner.calculate()
    served_from_precompute = getattr(response, "dataComputedAt", None) is not None
    return _results_to_dict(response.results), served_from_precompute


class Command(BaseCommand):
    help = "Compare marketing-analytics precompute vs live aggregated metrics per team."

    def add_arguments(self, parser: Any) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--teams", type=str, help="Comma-separated team ids.")
        group.add_argument("--teams-file", type=str, help="File with comma- or newline-separated team ids.")
        parser.add_argument("--date-from", type=str, default="-8d", help="Window start (default -8d).")
        parser.add_argument(
            "--date-to", type=str, default="-1d", help="Window end (default -1d; excludes today's stale bucket)."
        )
        parser.add_argument("--tolerance", type=float, default=1.0, help="Max %% diff per metric (default 1.0).")

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids = self._parse_team_ids(options)
        date_from: str = options["date_from"]
        date_to: str = options["date_to"]
        tolerance: float = options["tolerance"]

        teams = {t.id: t for t in Team.objects.filter(id__in=team_ids)}
        missing = sorted(set(team_ids) - set(teams.keys()))
        if missing:
            self.stderr.write(f"skipping {len(missing)} unknown team ids: {missing[:20]}")

        self.stdout.write(
            f"window {date_from}..{date_to}  tolerance {tolerance}%  teams {len(teams)}\n"
            f"{'team':>8}  {'metric':<28} {'precompute':>14} {'live':>14} {'diff%':>7}  status"
        )

        teams_pass = 0
        teams_failed: list[int] = []
        teams_vacuous: list[int] = []
        query = _aggregated_query(date_from=date_from, date_to=date_to)

        for team_id in team_ids:
            team = teams.get(team_id)
            if team is None:
                continue
            try:
                pre_metrics, served_from_precompute = _run(team, query, use_precompute=True)
                live_metrics, _ = _run(team, query, use_precompute=False)
            except Exception as exc:  # noqa: BLE001 — one bad team shouldn't abort the sweep
                self.stderr.write(f"{team_id}: query failed — {type(exc).__name__}: {exc}")
                teams_failed.append(team_id)
                continue

            # The precompute run fell back to live (no precomputable goal, or a build error), so a match
            # here compares live against live and proves nothing. Report it as vacuous, not a pass.
            if not served_from_precompute:
                teams_vacuous.append(team_id)
                self.stdout.write(f"{team_id:>8}  VACUOUS — precompute path fell back to live, comparison skipped")
                continue

            team_ok = True
            for name in sorted(set(pre_metrics) | set(live_metrics)):
                p = pre_metrics.get(name, 0.0)
                lv = live_metrics.get(name, 0.0)
                diff = _pct_diff(p, lv)
                ok = diff <= tolerance
                team_ok = team_ok and ok
                self.stdout.write(
                    f"{team_id:>8}  {name:<28} {p:>14.2f} {lv:>14.2f} {diff:>7.2f}  {'OK' if ok else 'OUT'}"
                )
            teams_pass += 1 if team_ok else 0
            if not team_ok:
                teams_failed.append(team_id)

        self.stdout.write(
            f"\nsummary: pass={teams_pass} out_of_tolerance={teams_failed} vacuous_fell_back_to_live={teams_vacuous}"
        )

    def _parse_team_ids(self, options: dict[str, Any]) -> list[int]:
        raw = options.get("teams")
        if not raw and options.get("teams_file"):
            with open(options["teams_file"]) as f:
                raw = f.read()
        if not raw:
            raise CommandError("provide --teams or --teams-file")
        ids: list[int] = []
        for token in raw.replace("\n", ",").split(","):
            token = token.strip()
            if token:
                ids.append(int(token))
        return ids
