"""Generate AI-suggested path-cleaning rules for web-analytics teams and print them for review.

Suggests only — applying rewrites historical numbers in every cleaned chart, so it stays a human
decision. `--apply` merges the generated rules into a team's existing `path_cleaning_filters`
(never overwriting) and is opt-in; review the printed suggestions first.

    # Default cohort (WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS), print + store health issues:
    python manage.py suggest_path_cleaning_rules

    # Specific teams, don't write health-issue rows (pure dry run):
    python manage.py suggest_path_cleaning_rules --teams 2,19279 --no-store

    # Generate and apply for one reviewed team:
    python manage.py suggest_path_cleaning_rules --teams 2 --apply
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team
from posthog.models.health_issue import HealthIssue

from products.web_analytics.backend.path_cleaning_suggestions.service import (
    DEFAULT_MIN_DISTINCT_PATHS,
    DEFAULT_SAMPLE_DAYS,
    DEFAULT_SAMPLE_LIMIT,
    DEFAULT_VISITED_WITHIN_DAYS,
    apply_suggestions_to_team,
    build_suggestion_payload,
    generate_suggestions_for_team,
)

SUGGESTIONS_KIND = "path_cleaning_suggestions"


class Command(BaseCommand):
    help = "Generate AI-suggested path-cleaning rules for web-analytics teams."

    def add_arguments(self, parser: Any) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--teams", type=str, help="Comma-separated team ids (default: configured cohort).")
        group.add_argument("--teams-file", type=str, help="File with comma- or newline-separated team ids.")
        parser.add_argument("--days", type=int, default=DEFAULT_SAMPLE_DAYS, help="Lookback window in days.")
        parser.add_argument("--limit", type=int, default=DEFAULT_SAMPLE_LIMIT, help="Top-N paths to sample.")
        parser.add_argument(
            "--min-distinct-paths",
            type=int,
            default=DEFAULT_MIN_DISTINCT_PATHS,
            help="Skip teams with fewer distinct paths than this (low cardinality => no value).",
        )
        parser.add_argument(
            "--include-configured",
            action="store_true",
            help="Also process teams that already have path cleaning rules (default: skip them).",
        )
        parser.add_argument(
            "--no-store", action="store_true", help="Don't persist suggestions as health issues (print only)."
        )
        parser.add_argument(
            "--visited-within-days",
            type=int,
            default=DEFAULT_VISITED_WITHIN_DAYS,
            help="Only process teams that opened Web analytics within this many days.",
        )
        parser.add_argument(
            "--ignore-visit-gate",
            action="store_true",
            help="Process teams even if they haven't recently opened Web analytics.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Merge generated rules into each team's path_cleaning_filters (never overwrites). Opt-in.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids = self._resolve_team_ids(options)
        teams = {t.id: t for t in Team.objects.filter(id__in=team_ids)}
        missing = sorted(set(team_ids) - set(teams.keys()))
        if missing:
            self.stderr.write(f"skipping {len(missing)} unknown team ids: {missing[:20]}")

        store = not options["no_store"]
        counts: dict[str, int] = {}
        applied_total = 0

        for team_id in team_ids:
            team = teams.get(team_id)
            if team is None:
                continue

            result = generate_suggestions_for_team(
                team,
                days=options["days"],
                limit=options["limit"],
                min_distinct_paths=options["min_distinct_paths"],
                include_configured=options["include_configured"],
                visited_within_days=None if options["ignore_visit_gate"] else options["visited_within_days"],
            )
            counts[result.status] = counts.get(result.status, 0) + 1
            self._print_team_result(team_id, result)

            issue = None
            if store and result.status == "generated" and result.rules:
                issue, _ = HealthIssue.upsert_issue(
                    team_id=team.id,
                    kind=SUGGESTIONS_KIND,
                    severity=HealthIssue.Severity.INFO,
                    payload=build_suggestion_payload(result),
                    hash_keys=[],
                )

            if options["apply"] and result.status == "generated" and result.rules:
                added = apply_suggestions_to_team(team, result.rules)
                applied_total += added
                if issue is not None and issue.status == HealthIssue.Status.ACTIVE:
                    issue.resolve()
                self.stdout.write(f"  applied {added} new rule(s) to team {team_id}")

        summary = "  ".join(f"{status}={n}" for status, n in sorted(counts.items()))
        self.stdout.write(f"\nsummary: {summary}  applied_rules={applied_total}")

    def _print_team_result(self, team_id: int, result: Any) -> None:
        if result.status != "generated":
            detail = f" — {result.error}" if result.error else ""
            self.stdout.write(f"team {team_id}: {result.status}{detail}")
            return

        self.stdout.write(
            f"team {team_id}: {len(result.rules)} rule(s) from {result.sampled_path_count} sampled paths "
            f"({result.distinct_path_count} distinct), model={result.model}"
        )
        for rule in result.rules:
            self.stdout.write(f"  [{rule.order}] {rule.regex}  ->  {rule.alias}  (matches {rule.match_count} paths)")
            for ex in rule.examples[:2]:
                self.stdout.write(f"        {ex['before']}  ->  {ex['after']}")

    def _resolve_team_ids(self, options: dict[str, Any]) -> list[int]:
        if options.get("teams"):
            return self._parse_ids(options["teams"])
        if options.get("teams_file"):
            with open(options["teams_file"]) as f:
                return self._parse_ids(f.read())
        cohort = settings.WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS
        if not cohort:
            raise CommandError(
                "no teams given and WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS is empty; "
                "pass --teams or --teams-file"
            )
        return list(cohort)

    def _parse_ids(self, raw: str) -> list[int]:
        ids: list[int] = []
        for token in raw.replace("\n", ",").split(","):
            token = token.strip()
            if token:
                ids.append(int(token))
        return ids
