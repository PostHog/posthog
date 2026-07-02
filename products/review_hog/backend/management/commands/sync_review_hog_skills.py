"""Sync canonical review-hog skills from disk to teams' LLMSkill rows.

Reads `products/review_hog/skills/` and reconciles each canonical skill against a team's `LLMSkill`
rows via the `sync_canonical_*` functions — the same ones the review run calls lazily at cold start;
this command is the impatient path:

- You merged a SKILL.md change and want it on a team now, not on its next review run.
- You're onboarding a team (e.g. seeding team 1 before an e2e run).

It seeds every review-hog skill set — the parallel-review **perspectives**, the **validation
criteria**, and the **blind-spot check**. `--all-teams` fans out to every team that already has
review-hog-seeded rows (the post-edit propagation).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from posthog.models.team.team import Team

from products.review_hog.backend.reviewer.lazy_seed import (
    REVIEW_HOG_SEEDED_BY,
    SyncResult,
    sync_canonical_blind_spots,
    sync_canonical_perspectives,
    sync_canonical_validation,
)
from products.skills.backend.models.skills import LLMSkill

# Every canonical-skill syncer ReviewHog owns; the command runs them all per team.
_SYNCERS: tuple[Callable[..., SyncResult], ...] = (
    sync_canonical_perspectives,
    sync_canonical_validation,
    sync_canonical_blind_spots,
)


class Command(BaseCommand):
    help = (
        "Sync canonical review-hog skills (perspectives + validation criteria + blind-spot check) "
        "from disk to teams' LLMSkill rows."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, help="Sync a specific team. Mutually exclusive with --all-teams.")
        parser.add_argument(
            "--all-teams",
            action="store_true",
            help="Sync every team that already has review-hog-seeded rows. Mutually exclusive with --team-id.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int | None = options.get("team_id")
        all_teams: bool = options.get("all_teams", False)
        dry_run: bool = options.get("dry_run", False)

        if not team_id and not all_teams:
            raise CommandError("Pass either --team-id <id> or --all-teams")
        if team_id and all_teams:
            raise CommandError("--team-id and --all-teams are mutually exclusive")

        teams = self._resolve_teams(team_id=team_id, all_teams=all_teams)
        if not teams:
            self.stdout.write(self.style.WARNING("No teams matched the selection — nothing to sync."))
            return

        if dry_run:
            self._dry_run(teams)
            return

        totals = {"created": 0, "updated": 0, "diverged": 0, "tombstoned": 0, "pruned": 0}
        for team in teams:
            # Explicit reconciliation → prune orphaned rows (canonical removed from disk).
            result = self._sync_team(team, prune=True)
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
                f"+{totals['created']} created, ~{totals['updated']} updated, "
                f"={totals['diverged']} diverged (left alone), "
                f"#{totals['tombstoned']} tombstoned, -{totals['pruned']} pruned"
            )
        )

    def _sync_team(self, team: Team, *, prune: bool) -> SyncResult:
        """Run every ReviewHog canonical-skill syncer for one team and merge the outcomes."""
        created: list[str] = []
        updated: list[str] = []
        diverged: list[str] = []
        tombstoned: list[str] = []
        pruned: list[str] = []
        skipped: list[str] = []
        for syncer in _SYNCERS:
            result = syncer(team, prune=prune)
            created += result.created_skill_names
            updated += result.updated_skill_names
            diverged += result.diverged_skill_names
            tombstoned += result.tombstoned_skill_names
            pruned += result.pruned_skill_names
            if result.skipped_reason:
                skipped.append(result.skipped_reason)
        any_change = bool(created or updated or diverged or tombstoned or pruned)
        return SyncResult(
            created_skill_names=tuple(created),
            updated_skill_names=tuple(updated),
            diverged_skill_names=tuple(diverged),
            tombstoned_skill_names=tuple(tombstoned),
            pruned_skill_names=tuple(pruned),
            # Only a true skip when nothing across all syncers had any canonical to reconcile.
            skipped_reason="; ".join(skipped) if skipped and not any_change else None,
        )

    def _resolve_teams(self, *, team_id: int | None, all_teams: bool) -> list[Team]:
        if team_id:
            try:
                return [Team.objects.get(id=team_id)]
            except Team.DoesNotExist:
                raise CommandError(f"Team {team_id} not found")
        # all_teams — every team that already has at least one review-hog-seeded skill, so a SKILL.md
        # edit fans out to teams that have run a review before.
        team_ids = (
            LLMSkill.objects.filter(metadata__seeded_by=REVIEW_HOG_SEEDED_BY)
            .values_list("team_id", flat=True)
            .distinct()
        )
        return list(Team.objects.filter(id__in=list(team_ids)).order_by("id"))

    def _dry_run(self, teams: list[Team]) -> None:
        # A transaction-rolled-back sync, so the per-team report reflects what would happen.
        self.stdout.write(self.style.WARNING("[dry-run] no changes will be persisted"))
        with transaction.atomic():
            for team in teams:
                result = self._sync_team(team, prune=True)
                self._print_team_result(team, result, prefix="[dry-run] ")
            transaction.set_rollback(True)

    def _print_team_result(self, team: Team, result: SyncResult, prefix: str = "") -> None:
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
        self.stdout.write(f"{prefix}team {team.id}: " + (", ".join(parts) if parts else "no changes"))
