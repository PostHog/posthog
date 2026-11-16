import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from asgiref.sync import async_to_sync

from posthog.models import Team
from posthog.storage import object_storage

from products.signals.backend.temporal.refusal_review import reingest_held_signal


class Command(BaseCommand):
    help = (
        "Re-ingest signals held for review by the safety filter into the active pipeline "
        "after human or judge confirmation that they are benign."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="The ID of the team.")
        parser.add_argument("--key", type=str, help="Specific object storage key of the held signal to reingest.")
        parser.add_argument("--fingerprint", type=str, help="Fingerprint hash of the held signal.")
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all signals currently held for review for the team without reingesting.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-ingest all signals currently held for review for the team.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        key: str | None = options.get("key")
        fingerprint: str | None = options.get("fingerprint")
        list_mode: bool = options.get("list", False)
        all_mode: bool = options.get("all", False)

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist as err:
            raise CommandError(f"Team {team_id} not found") from err

        prefix = f"signals/refusal_review/{team_id}/"

        if list_mode:
            keys = object_storage.list_objects(prefix) or []
            if not keys:
                self.stdout.write(self.style.NOTICE(f"No signals currently held for review for team {team_id} ({team.name})."))
                return

            self.stdout.write(self.style.SUCCESS(f"Found {len(keys)} signal(s) held for review for team {team_id}:"))
            for k in keys:
                raw = object_storage.read(k, missing_ok=True)
                desc = ""
                reason = "unknown"
                if raw:
                    try:
                        data = json.loads(raw)
                        reason = data.get("reason", "unknown")
                        desc = data.get("signal", {}).get("description", "")[:80]
                    except Exception:
                        pass
                self.stdout.write(f"  • Key: {k}")
                self.stdout.write(f"    Reason: {reason} | Excerpt: {desc}...")
            return

        if all_mode:
            keys = object_storage.list_objects(prefix) or []
            if not keys:
                self.stdout.write(self.style.NOTICE(f"No signals held for review to reingest for team {team_id}."))
                return

            success_count = 0
            for k in keys:
                success = async_to_sync(reingest_held_signal)(team_id=team_id, key=k)
                if success:
                    success_count += 1
                    self.stdout.write(self.style.SUCCESS(f"Re-ingested held signal: {k}"))
                else:
                    self.stdout.write(self.style.ERROR(f"Failed to reingest held signal: {k}"))

            self.stdout.write(
                self.style.SUCCESS(f"Completed re-ingestion: {success_count}/{len(keys)} signals re-ingested.")
            )
            return

        if not key and not fingerprint:
            raise CommandError("Must provide --key, --fingerprint, --list, or --all.")

        success = async_to_sync(reingest_held_signal)(team_id=team_id, key=key, fingerprint=fingerprint)
        if success:
            self.stdout.write(
                self.style.SUCCESS(f"Successfully re-ingested held signal for team {team_id} ({key or fingerprint}).")
            )
        else:
            raise CommandError(f"Failed to reingest held signal for team {team_id} ({key or fingerprint}).")
