from argparse import ArgumentParser
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.scout_harness.config_registry import (
    resume_setup_paused_operational_config,
    setup_paused_operational_configs,
)
from products.signals.backend.scout_harness.team_limits import (
    _canonicalize_team_config_keys,
    _default_team_config,
    _read_flag_payload,
    _resolve_withheld_skills,
    _team_configs,
    resolve_max_enabled_scouts,
)


@dataclass(frozen=False)
class ResumeSummary:
    selected: Counter[str] = field(default_factory=Counter)
    resumed: Counter[str] = field(default_factory=Counter)
    skipped_withheld: Counter[str] = field(default_factory=Counter)
    not_resumed: Counter[str] = field(default_factory=Counter)
    team_ids: list[int] = field(default_factory=list)


def resume_setup_paused_operational_scouts(
    *, apply: bool, team_id: int | None, batch_size: int, max_gap: timedelta
) -> ResumeSummary:
    # One flag read for the whole run, so every team resolves its holdback and cap from one payload.
    payload = _read_flag_payload()
    team_configs = _canonicalize_team_config_keys(_team_configs(payload))
    default_team_config = _default_team_config(payload)

    summary = ResumeSummary()
    seen_team_ids: set[int] = set()
    # A pk cursor rather than re-reading the first page: a row this run skips still matches.
    after_pk = None
    while True:
        configs = setup_paused_operational_configs(max_gap=max_gap, team_id=team_id).order_by("pk")
        if after_pk is not None:
            configs = configs.filter(pk__gt=after_pk)
        batch = list(configs[:batch_size])
        if not batch:
            return summary
        for config in batch:
            summary.selected[config.skill_name] += 1
            if config.team_id not in seen_team_ids:
                seen_team_ids.add(config.team_id)
                summary.team_ids.append(config.team_id)
            if config.skill_name in _resolve_withheld_skills(config.team_id, team_configs, default_team_config):
                summary.skipped_withheld[config.skill_name] += 1
                continue
            if not apply:
                continue
            max_enabled_scouts = resolve_max_enabled_scouts(
                [team_configs.get(config.team_id) or {}, default_team_config]
            )
            if resume_setup_paused_operational_config(config, max_enabled_scouts=max_enabled_scouts):
                summary.resumed[config.skill_name] += 1
            else:
                summary.not_resumed[config.skill_name] += 1
        after_pk = batch[-1].pk


class Command(BaseCommand):
    help = (
        "Resume operational scouts (such as inbox validation) that the old self-driving setup flow "
        "switched off seconds after the seed. A pause a person made is left alone. Dry run unless "
        "--apply is passed. Safe to rerun: a resumed row no longer matches."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Print what would change. The default.")
        mode.add_argument("--apply", action="store_true", help="Resume the selected scouts.")
        parser.add_argument("--team-id", type=int, help="Limit the run to one project.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument(
            "--max-gap-seconds",
            type=int,
            default=300,
            help="Longest time between the seed and the pause for the pause to count as the setup flow's.",
        )
        parser.add_argument("--show-team-ids", type=int, default=20, help="How many team ids to print.")

    def handle(self, *args: object, **options: object) -> None:
        apply = bool(options["apply"])
        summary = resume_setup_paused_operational_scouts(
            apply=apply,
            team_id=cast(int | None, options["team_id"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 5000)),
            max_gap=timedelta(seconds=max(0, cast(int, options["max_gap_seconds"]))),
        )
        self.stdout.write("Mode: apply" if apply else "Mode: dry run (pass --apply to write)")
        for skill_name, count in sorted(summary.selected.items()):
            line = f"{skill_name}: selected {count}, withheld {summary.skipped_withheld[skill_name]}"
            if apply:
                line += f", resumed {summary.resumed[skill_name]}, not resumed {summary.not_resumed[skill_name]}"
            self.stdout.write(line)
        shown = summary.team_ids[: cast(int, options["show_team_ids"])]
        self.stdout.write(f"Teams: {len(summary.team_ids)}. First team ids: {shown}")
