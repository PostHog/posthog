"""Backtests the observation windows of flag rollback suggestions on the history of one team.

Run it with `--count-only` first: it reads only Postgres and counts the windows and rollbacks of the range. The full run
reads ClickHouse once per day of edits and stores what it read in `--data` after each day. A rerun with the same
`--data` reads only what the file lacks, so it resumes a failed run, and a change of parameters costs no query.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from pydantic import ValidationError

from posthog.models import Team

from products.feature_flags.backend.flag_windows.backtest import (
    DEFAULT_PARAMETERS,
    BacktestData,
    Candidates,
    WindowResult,
    dump_data,
    fetch_data,
    find_candidates,
    load_data,
    run_backtest,
    summarize,
)
from products.feature_flags.backend.flag_windows.history import flag_histories, owned_flag_ids


class Command(BaseCommand):
    help = "Backtest the flag observation windows on the flag history of a team. Read-only."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--start", type=datetime.fromisoformat, required=True, help="ISO date of the first edit")
        parser.add_argument("--end", type=datetime.fromisoformat, required=True, help="ISO date after the last edit")
        parser.add_argument("--output", type=Path, required=True, help="Path of the JSON report")
        parser.add_argument("--count-only", action="store_true", help="Count windows and rollbacks, no ClickHouse")
        parser.add_argument("--data", type=Path, help="JSON file to store the query results in, or to read them from")

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(pk=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team {options['team_id']}")
        start, end = _utc(options["start"]), _utc(options["end"])
        if end <= start:
            raise CommandError("--end must come after --start")
        parameters = DEFAULT_PARAMETERS

        histories = {history.flag_id: history for history in flag_histories(team.pk, start)}
        excluded = owned_flag_ids(team.pk, histories)
        candidates = find_candidates(histories.values(), start, end, parameters, excluded)
        self.stdout.write(
            f"{len(candidates.windows)} windows, "
            f"{sum(1 for window in candidates.windows if window.rollback is not None)} rollbacks, "
            f"{len(candidates.misses)} rollbacks without a window, {len(excluded)} flags owned by other products, "
            f"{sum(history.mismatches for history in histories.values())} activity log entries that differ from the "
            "rebuilt config"
        )

        if options["count_only"]:
            report: dict[str, Any] = {
                "windows": len(candidates.windows),
                "rollbacks": sum(1 for window in candidates.windows if window.rollback is not None),
                "rollback_reasons": _count(window.rollback.reason for window in candidates.windows if window.rollback),
                "trigger_misses": len(candidates.misses),
                "trigger_miss_reasons": _count(miss.reason for miss in candidates.misses),
                "unreadable_edits": candidates.unreadable,
                "excluded_flags": len(excluded),
                "history_mismatches": sum(history.mismatches for history in histories.values()),
            }
        else:
            data = self._data(team, candidates, options["data"])
            results = run_backtest(candidates, histories, data, parameters)
            report = {
                "summary": summarize(results, candidates, start, end),
                "windows": [_row(result) for result in results],
            }
        options["output"].write_text(json.dumps(report, indent=2, default=str))
        self.stdout.write(f"Report written to {options['output']}")

    def _data(self, team: Team, candidates: Candidates, path: Path | None) -> BacktestData:
        earlier = None
        if path is not None and path.exists():
            try:
                earlier = load_data(path.read_bytes())
            except ValidationError as error:
                raise CommandError(f"{path} doesn't hold backtest data: {error}") from error
            if earlier.team_id != team.pk:
                raise CommandError(f"{path} holds the backtest data of team {earlier.team_id}, not of team {team.pk}")

        def checkpoint(data: BacktestData) -> None:
            if path is not None:
                # A run that stops during the write keeps the previous checkpoint whole.
                partial = path.with_name(f"{path.name}.partial")
                partial.write_bytes(dump_data(data))
                partial.replace(path)

        return fetch_data(
            team, candidates.windows, DEFAULT_PARAMETERS, timezone.now(), earlier=earlier, checkpoint=checkpoint
        )


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        name = str(value) if value is not None else "none"
        counts[name] = counts.get(name, 0) + 1
    return counts


def _row(result: WindowResult) -> dict[str, Any]:
    """One window of the report. The configs stay out, because their filters can hold person property values."""
    window, rollback, evidence = result.window, result.window.rollback, result.evidence
    return {
        "edit_id": window.edit.id,
        "flag_id": window.flag_id,
        "flag_key": window.edit.flag_key,
        "edited_at": window.edit.edited_at.isoformat(),
        "kinds": sorted(window.kinds),
        "watched_conditions": [condition.position for condition in window.edit.conditions],
        "rollback": {
            "at": rollback.at.isoformat(),
            "activity_log_id": rollback.activity_log_id,
            "reason": rollback.reason,
        }
        if rollback
        else None,
        "label": result.label,
        "evidence": evidence and {name: getattr(evidence, name) for name in evidence.__dataclass_fields__},
        "replays": {
            match: {
                "suspicious_at": replay.suspicious_at and replay.suspicious_at.isoformat(),
                "close_reason": replay.close_reason,
                "closed_at": replay.closed_at and replay.closed_at.isoformat(),
                "max_score": replay.max_score,
            }
            for match, replay in result.replays.items()
        },
    }
