from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.replay_vision.backend.sampling_mode_retirement import retire_sampling_modes


class Command(BaseCommand):
    help = "Switch focused and balanced scanners to comprehensive, scaling each sampling rate so volume holds"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--apply", action="store_true", help="Write the changes; without it, only report them")
        parser.add_argument("--team-id", type=int, action="append", help="Only this team; repeat for more")

    def handle(self, *args: Any, **options: Any) -> None:
        apply = bool(options["apply"])
        retired = retire_sampling_modes(apply=apply, team_ids=options["team_id"])
        for r in retired:
            self.stdout.write(
                f"{r.scanner_id} team={r.team_id} mode={r.sampling_mode} "
                f"rate {r.old_rate:.4f} -> {r.new_rate:.4f}{' (pooled share)' if r.pooled_share else ''}"
            )
        modes = Counter(r.sampling_mode for r in retired)
        pooled = sum(r.pooled_share for r in retired)
        verb = "Retired" if apply else "Would retire"
        self.stdout.write(
            f"{verb} {len(retired)} scanners ({modes.get('focused', 0)} focused, {modes.get('balanced', 0)} balanced), "
            f"{pooled} on the pooled share."
        )
