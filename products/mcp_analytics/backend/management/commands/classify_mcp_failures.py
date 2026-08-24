"""Staff tool: classify recent MCP tool-call failures by cause and print a breakdown.

Thin and throwaway-grade on purpose — no caching tables, no snapshots, no feature flag. Reads
``$mcp_tool_call`` failures from ClickHouse, groups raw messages into normalized fingerprints, and
classifies each fingerprint with a batched LLM call (see ``failure_classification.py``).
"""

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team
from posthog.security.spreadsheet_safety import sanitize_formula_injection

from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.failure_classification import (
    FailureClass,
    FailureClassificationUnavailable,
    classify_fingerprints,
    normalize_fingerprint,
)

EXAMPLE_MAX_CHARS = 80


def _clean(value: str) -> str:
    """Raw messages carry tabs and newlines; keep the TSV/stdout tables one row per record.

    Values are event-sender-controlled, so exported cells also get formula-injection
    sanitization — staff will open this file in a spreadsheet.
    """
    flattened = value.replace("\t", " ").replace("\n", " | ").replace("\r", "")
    sanitized: str = sanitize_formula_injection(flattened)
    return sanitized


_FAILURES_SQL = """
SELECT
    toString(properties.$mcp_tool_name) AS tool,
    toString(properties.$mcp_error_message) AS message,
    count() AS events,
    uniq(distinct_id) AS users
FROM events
WHERE event = {event}
    AND timestamp >= {date_from}
    AND toBool(properties.$mcp_is_error)
    AND isNotNull(properties.$mcp_error_message)
GROUP BY tool, message
ORDER BY events DESC
"""


@dataclass
class FingerprintAggregate:
    events: int = 0
    # Summed per-(tool, message) uniq counts: a user who hit several raw messages sharing one
    # fingerprint is counted once per message, so this is an upper bound. An exact uniq would
    # need the fingerprinting pushed into SQL, duplicating normalize_fingerprint and inviting
    # drift; a bound is enough for ranking in a staff tool.
    users_upper_bound: int = 0
    tools: set[str] = field(default_factory=set)
    example_message: str = ""
    example_events: int = 0


def fetch_failure_rows(team: Team, days: int) -> list[tuple[str, str, int, int]]:
    """Return (tool, raw_message, event_count, user_count) rows for the team's recent failures."""
    query = parse_select(
        _FAILURES_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "date_from": ast.Constant(value=timezone.now() - timedelta(days=days)),
        },
    )
    with tags_context(
        product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=team.id, name="classify_mcp_failures_command"
    ):
        response = execute_hogql_query(query=query, team=team)
    return [
        (str(row[0] or ""), str(row[1] or ""), int(row[2] or 0), int(row[3] or 0)) for row in (response.results or [])
    ]


def aggregate_by_fingerprint(
    rows: list[tuple[str, str, int, int]], max_fingerprints: int
) -> dict[str, FingerprintAggregate]:
    """Group raw (tool, message) rows into fingerprints, keeping a representative message each.

    ``rows`` come from ClickHouse ordered by event count descending, so the first raw message seen
    for a fingerprint is its most common phrasing — that's what gets kept as the example.
    """
    aggregates: dict[str, FingerprintAggregate] = {}
    for tool, message, events, users in rows:
        fingerprint = normalize_fingerprint(message)
        if not fingerprint:
            continue
        aggregate = aggregates.get(fingerprint)
        if aggregate is None:
            if len(aggregates) >= max_fingerprints:
                continue
            aggregate = FingerprintAggregate()
            aggregates[fingerprint] = aggregate
        aggregate.events += events
        aggregate.users_upper_bound += users
        if tool:
            aggregate.tools.add(tool)
        if events > aggregate.example_events:
            aggregate.example_message = message
            aggregate.example_events = events
    return aggregates


class Command(BaseCommand):
    help = "Classify MCP tool-call failures by cause and print a per-class breakdown."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to classify failures for.")
        parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default: 30).")
        parser.add_argument(
            "--max-fingerprints", type=int, default=500, help="Cap on distinct fingerprints classified (default: 500)."
        )
        parser.add_argument("--output", type=str, default=None, help="Optional TSV path for per-fingerprint rows.")
        parser.add_argument("--dry-run", action="store_true", help="Skip the LLM; print fingerprint counts only.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        days: int = options["days"]
        max_fingerprints: int = options["max_fingerprints"]
        output: str | None = options["output"]
        dry_run: bool = options["dry_run"]

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team {team_id} does not exist."))
            return

        rows = fetch_failure_rows(team, days)
        total_failures = sum(row[2] for row in rows)
        aggregates = aggregate_by_fingerprint(rows, max_fingerprints)

        self.stdout.write(f"Total failures: {total_failures}")
        self.stdout.write(f"Distinct fingerprints: {len(aggregates)}")

        if dry_run:
            self._print_dry_run(aggregates)
            return

        try:
            classifications = classify_fingerprints(
                {fingerprint: aggregate.example_message for fingerprint, aggregate in aggregates.items()}, team
            )
        except FailureClassificationUnavailable as e:
            self.stderr.write(self.style.ERROR(f"Cannot classify: {e}"))
            return
        self._print_breakdown(aggregates, classifications, total_failures)
        if output:
            self._write_tsv(output, aggregates, classifications)

    def _print_dry_run(self, aggregates: dict[str, FingerprintAggregate]) -> None:
        self.stdout.write("\nfingerprint\tevents\tusers_upper_bound\texample")
        for fingerprint, aggregate in sorted(aggregates.items(), key=lambda item: item[1].events, reverse=True):
            example = _clean(aggregate.example_message)[:EXAMPLE_MAX_CHARS]
            self.stdout.write(f"{fingerprint}\t{aggregate.events}\t{aggregate.users_upper_bound}\t{example}")

    def _print_breakdown(
        self,
        aggregates: dict[str, FingerprintAggregate],
        classifications: dict[str, str],
        total_failures: int,
    ) -> None:
        by_class: dict[str, list[str]] = defaultdict(list)
        for fingerprint in aggregates:
            failure_class = classifications.get(fingerprint, FailureClass.INTERNAL_ERROR.value)
            by_class[failure_class].append(fingerprint)

        self.stdout.write("\nclass\tevents\tshare%\tfingerprints\texample")
        rows = []
        for failure_class, fingerprints in by_class.items():
            events = sum(aggregates[f].events for f in fingerprints)
            share = round(events * 100.0 / total_failures, 1) if total_failures else 0.0
            example_fingerprint = max(fingerprints, key=lambda f: aggregates[f].events)
            example = _clean(aggregates[example_fingerprint].example_message)[:EXAMPLE_MAX_CHARS]
            rows.append((failure_class, events, share, len(fingerprints), example))

        for failure_class, events, share, fingerprint_count, example in sorted(
            rows, key=lambda row: row[1], reverse=True
        ):
            self.stdout.write(f"{failure_class}\t{events}\t{share}\t{fingerprint_count}\t{example}")

    def _write_tsv(
        self,
        output: str,
        aggregates: dict[str, FingerprintAggregate],
        classifications: dict[str, str],
    ) -> None:
        with open(output, "w", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(["fingerprint", "class", "events", "users_upper_bound", "tools", "example"])
            for fingerprint, aggregate in sorted(aggregates.items(), key=lambda item: item[1].events, reverse=True):
                failure_class = classifications.get(fingerprint, FailureClass.INTERNAL_ERROR.value)
                writer.writerow(
                    [
                        _clean(fingerprint),
                        failure_class,
                        aggregate.events,
                        aggregate.users_upper_bound,
                        _clean(",".join(sorted(aggregate.tools))),
                        _clean(aggregate.example_message)[:EXAMPLE_MAX_CHARS],
                    ]
                )
        self.stdout.write(f"\nWrote {len(aggregates)} rows to {output}")
