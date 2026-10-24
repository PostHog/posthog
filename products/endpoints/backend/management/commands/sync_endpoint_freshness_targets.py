"""Make each materialized endpoint version's node target match the version's declared data freshness.

Dry run by default: lists the mismatches and changes nothing. `--apply` writes the declared freshness to
the node and reconciles its DAG's tier schedules. A freshness the node's sources cannot deliver is
refused and left as it is. Run it once per region.

    python manage.py sync_endpoint_freshness_targets
    python manage.py sync_endpoint_freshness_targets --team-id 2 --apply
"""

from collections import Counter
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.endpoints.backend.logic.freshness_targets import find_freshness_target_mismatches, repair_freshness_target


def _seconds(value: timedelta | None) -> str:
    return "none" if value is None else str(int(value.total_seconds()))


class Command(BaseCommand):
    help = "Align endpoint node freshness targets with the endpoint's declared data freshness."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only this team.")
        parser.add_argument("--apply", action="store_true", help="Write the targets. Without it, report only.")
        parser.add_argument("--verbose-rows", action="store_true", help="Print one line per mismatched version.")

    def handle(self, *args: Any, **options: Any) -> None:
        apply: bool = options["apply"]
        mismatches = list(find_freshness_target_mismatches(team_id=options["team_id"]))

        pairs = Counter((_seconds(m.node_target), _seconds(m.declared)) for m in mismatches)
        self.stdout.write(f"{len(mismatches)} mismatched endpoint version(s)")
        for (node_target, declared), count in sorted(pairs.items()):
            self.stdout.write(f"  node target {node_target}s -> declared {declared}s: {count}")

        if not apply:
            if options["verbose_rows"]:
                for m in mismatches:
                    self.stdout.write(self._row(m.version, m.node_target, m.declared))
            self.stdout.write("Dry run. Pass --apply to write.")
            return

        written = refused = nodeless = 0
        for mismatch in mismatches:
            outcome = repair_freshness_target(mismatch)
            if outcome.refused_reason is not None:
                refused += 1
                self.stdout.write(
                    f"REFUSED {self._row(mismatch.version, mismatch.node_target, mismatch.declared)}"
                    f" reason={outcome.refused_reason}"
                )
            elif outcome.nodes_written == 0:
                nodeless += 1
                self.stdout.write(f"NO NODE {self._row(mismatch.version, mismatch.node_target, mismatch.declared)}")
            else:
                written += 1
                if options["verbose_rows"]:
                    self.stdout.write(f"FIXED {self._row(mismatch.version, mismatch.node_target, mismatch.declared)}")
        self.stdout.write(f"fixed={written} refused={refused} no_node={nodeless}")

    @staticmethod
    def _row(version: Any, node_target: timedelta | None, declared: timedelta) -> str:
        return (
            f"team={version.endpoint.team_id} endpoint={version.endpoint.name} version={version.version}"
            f" saved_query={version.saved_query_id} node_target={_seconds(node_target)} declared={_seconds(declared)}"
        )
