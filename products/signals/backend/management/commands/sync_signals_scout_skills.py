"""Force a `sync_canonical_skills` pass for one or more teams without waiting for the
coordinator tick.

Use cases:

- You merged a SKILL.md change and want it propagated to dogfood teams *now*, not on the
  next ≤15min coordinator tick.
- You shipped a quick revert and want every team back to the fixed canonical immediately.
- You're onboarding a new team and want the canonical fleet seeded synchronously.

Reads the canonical fleet from `products/signals/skills/signals-scout-*/` (whatever the
worker process sees on disk), then calls `sync_canonical_skills(team)` per team. Same
function the coordinator and runner call lazily — this command is just the impatient path.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posthog.models.team.team import Team

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import sync_canonical_skills
from products.signals.backend.scout_harness.team_limits import withheld_skills_for_team


class Command(BaseCommand):
    help = "Sync canonical signals-scout-* skills from disk to teams' LLMSkill rows."

    def add_arguments(self, parser):
        # `--team-id` and `--all-enabled` are mutually exclusive; one is required. Plain
        # default would either skip everything or fan out to the whole DB without intent.
        parser.add_argument(
            "--team-id",
            type=int,
            help="Sync a specific team. Mutually exclusive with --all-enabled.",
        )
        parser.add_argument(
            "--all-enabled",
            action="store_true",
            help=(
                "Sync every team that has an enabled SignalScoutConfig. Use this after "
                "merging a SKILL.md change to fan it out to all dogfood teams."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing to the DB.",
        )

    def handle(self, *args, **options):
        team_id: int | None = options.get("team_id")
        all_enabled: bool = options.get("all_enabled", False)
        dry_run: bool = options.get("dry_run", False)

        if not team_id and not all_enabled:
            raise CommandError("Pass either --team-id <id> or --all-enabled")
        if team_id and all_enabled:
            raise CommandError("--team-id and --all-enabled are mutually exclusive")

        teams = self._resolve_teams(team_id=team_id, all_enabled=all_enabled)
        if not teams:
            self.stdout.write(self.style.WARNING("No teams matched the selection — nothing to sync."))
            return

        if dry_run:
            # Dry-run is a transaction-rolled-back sync so we get the real per-team report
            # without persisting. Pulled into a separate helper to keep the no-op path
            # obvious; callers can lean on the output to decide whether to run for real.
            self._dry_run(teams)
            return

        totals = {
            "created": 0,
            "updated": 0,
            "diverged": 0,
            "tombstoned": 0,
            "pruned": 0,
        }
        for team in teams:
            # Explicit reconciliation path → prune orphaned rows (canonical removed from disk).
            # Honor the per-scout holdback denylist so this impatient fan-out can't seed a
            # withheld scout's LLMSkill rows onto a held-back team (the coordinator gates the
            # scheduled path the same way).
            result = sync_canonical_skills(team, prune=True, withheld_skill_names=withheld_skills_for_team(team.id))
            totals["created"] += len(result.created_skill_names)
            totals["updated"] += len(result.updated_skill_names)
            totals["diverged"] += len(result.diverged_skill_names)
            totals["tombstoned"] += len(result.tombstoned_skill_names)
            totals["pruned"] += len(result.pruned_skill_names)
            self._print_team_result(team, result)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced {len(teams)} team(s): "
                f"+{totals['created']} created, "
                f"~{totals['updated']} updated, "
                f"={totals['diverged']} diverged (left alone), "
                f"#{totals['tombstoned']} tombstoned, "
                f"-{totals['pruned']} pruned"
            )
        )

    def _resolve_teams(self, *, team_id: int | None, all_enabled: bool) -> list[Team]:
        if team_id:
            try:
                return [Team.objects.get(id=team_id)]
            except Team.DoesNotExist:
                raise CommandError(f"Team {team_id} not found")
        # all_enabled — pull every team that has at least one enabled SignalScoutConfig.
        # `.unscoped()` is intentional: this is a cross-team management scan, same as the
        # Temporal coordinator. The default `.objects` manager is fail-closed
        # (TeamScopedRootMixin) so without the unscoped sibling it would either raise or
        # silently return only the team in the current scope context, hiding teams the
        # operator is trying to sync.
        # `select_related("team")` to avoid an N+1 in the loop above.
        configs = SignalScoutConfig.objects.unscoped().filter(enabled=True).select_related("team").order_by("team__id")
        # Distinct teams only; one config per team is the norm but we don't depend on it.
        seen: set[int] = set()
        teams: list[Team] = []
        for config in configs:
            if config.team.id in seen:
                continue
            seen.add(config.team.id)
            teams.append(config.team)
        return teams

    def _dry_run(self, teams: list[Team]) -> None:
        # Run inside a transaction we always roll back, so the output reflects what *would*
        # happen if we ran for real. Cheaper than re-implementing the decision branches here.
        self.stdout.write(self.style.WARNING("[dry-run] no changes will be persisted"))
        with transaction.atomic():
            for team in teams:
                # Preview prune too (rolled back below), so the dry-run shows what would be reaped.
                # Same holdback resolution as the real run so the preview matches what would seed.
                result = sync_canonical_skills(team, prune=True, withheld_skill_names=withheld_skills_for_team(team.id))
                self._print_team_result(team, result, prefix="[dry-run] ")
            transaction.set_rollback(True)

    def _print_team_result(self, team: Team, result, prefix: str = "") -> None:
        if result.skipped_reason:
            self.stdout.write(f"{prefix}team {team.id}: skipped — {result.skipped_reason}")
            return
        parts: list[str] = []
        if result.created_skill_names:
            parts.append(f"+created {list(result.created_skill_names)}")
        if result.updated_skill_names:
            parts.append(f"~updated {list(result.updated_skill_names)}")
        if result.diverged_skill_names:
            parts.append(f"=diverged {list(result.diverged_skill_names)}")
        if result.tombstoned_skill_names:
            parts.append(f"#tombstoned {list(result.tombstoned_skill_names)}")
        if result.pruned_skill_names:
            parts.append(f"-pruned {list(result.pruned_skill_names)}")
        if not parts:
            self.stdout.write(f"{prefix}team {team.id}: no changes")
            return
        self.stdout.write(f"{prefix}team {team.id}: " + ", ".join(parts))
