from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.models import Team
from posthog.models.scoping.manager import resolve_effective_team_id

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun, SignalScratchpad
from products.signals.backend.scout_harness.tools.scratchpad import _creator_filter

logger = structlog.get_logger(__name__)

RECENT_RUN_WINDOW = timedelta(hours=24)


class Command(BaseCommand):
    help = (
        "Permanently delete SignalScratchpad entries for one team, chosen by scout, by key, or all. "
        "Preview only unless --execute is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team (project) that owns the entries.")
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument(
            "--scout-skill", help="Delete the entries runs of this scout created (or a pipeline:* writer's entries)."
        )
        selection.add_argument("--keys", nargs="+", help="Delete the entries with these exact keys.")
        selection.add_argument("--all", action="store_true", help="Delete every entry of the team.")
        parser.add_argument("--execute", action="store_true", help="Write. Without it the command only previews.")

    def handle(self, *args, **options):
        if not Team.objects.filter(id=options["team_id"]).exists():
            raise CommandError(f"Team {options['team_id']} does not exist.")
        team_id = resolve_effective_team_id(options["team_id"])
        if team_id != options["team_id"]:
            self.stdout.write(f"Team {options['team_id']} is an environment; using its project team {team_id}.")

        entries = SignalScratchpad.objects.for_team(team_id, canonical=True)
        selected = entries
        if options["scout_skill"]:
            selected = entries.filter(_creator_filter(team_id=team_id, skill_name=options["scout_skill"]))
        elif options["keys"]:
            selected = entries.filter(key__in=options["keys"])
        selected_keys = sorted(selected.values_list("key", flat=True))
        kept_keys = sorted(entries.exclude(key__in=selected_keys).values_list("key", flat=True))

        self.stdout.write(f"Would delete {len(selected_keys)} entr(ies):")
        for key in selected_keys:
            self.stdout.write(f"  - {key}")
        self.stdout.write(f"Would keep {len(kept_keys)} entr(ies):")
        for key in kept_keys:
            self.stdout.write(f"  = {key}")
        if options["keys"]:
            missing = sorted(set(options["keys"]) - set(selected_keys))
            if missing:
                self.stdout.write(self.style.WARNING(f"No entry for key(s): {', '.join(missing)}"))
        self._warn_if_scouts_active(team_id, options["scout_skill"])

        if not options["execute"]:
            self.stdout.write(self.style.SUCCESS("Preview only. Nothing was written. Pass --execute to delete."))
            return
        if not selected_keys:
            self.stdout.write("Nothing to delete.")
            return

        with transaction.atomic():
            locked_keys = sorted(
                SignalScratchpad.objects.for_team(team_id, canonical=True)
                .filter(key__in=selected_keys)
                .select_for_update()
                .values_list("key", flat=True)
            )
            if locked_keys != selected_keys:
                raise CommandError("Entries changed since the preview. Nothing was deleted; run the command again.")
            _, deleted_rows = (
                SignalScratchpad.objects.for_team(team_id, canonical=True).filter(key__in=selected_keys).delete()
            )
            deleted = deleted_rows.get(SignalScratchpad._meta.label, 0)
            if deleted != len(selected_keys):
                raise CommandError(
                    f"Deleted {deleted} entr(ies), expected {len(selected_keys)}. Rolled back; nothing was deleted."
                )

        logger.info("signals.purge_signal_scratchpad.completed", team_id=team_id, keys=selected_keys)
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} scratchpad entr(ies) for team {team_id}."))

    def _warn_if_scouts_active(self, team_id: int, skill_name: str | None) -> None:
        configs = SignalScoutConfig.objects.for_team(team_id, canonical=True).filter(enabled=True)
        runs = SignalScoutRun.objects.for_team(team_id, canonical=True).filter(
            created_at__gte=timezone.now() - RECENT_RUN_WINDOW
        )
        if skill_name:
            configs = configs.filter(skill_name=skill_name)
            runs = runs.filter(skill_name=skill_name)
        enabled = sorted(configs.values_list("skill_name", flat=True))
        if enabled:
            self.stdout.write(
                self.style.WARNING(
                    f"Enabled scouts can write new entries during the delete: {', '.join(enabled)}. "
                    "Pause them first if the request covers future entries too."
                )
            )
        if runs.exists():
            self.stdout.write(self.style.WARNING("A scout ran in the last 24 hours and may still be running."))
