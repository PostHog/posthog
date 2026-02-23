import json
import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.signals.backend.api import emit_signal

DEFAULT_INPUT_DIR = Path(__file__).resolve().parent.parent.parent / "github_issues" / "posthog" / "posthog"

EXTRA_FIELDS = ("html_url", "number", "labels", "created_at", "updated_at", "locked", "state")


class Command(BaseCommand):
    help = "Ingest downloaded GitHub issue JSON files as signals via emit_signal()"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to emit signals for",
        )
        parser.add_argument(
            "--input-dir",
            type=str,
            default=None,
            help=f"Directory containing issue JSON files (default: {DEFAULT_INPUT_DIR})",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        input_dir = Path(options["input_dir"]) if options["input_dir"] else DEFAULT_INPUT_DIR
        if not input_dir.exists():
            raise CommandError(f"Input directory does not exist: {input_dir}")

        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} not found")

        json_files = sorted(
            [p for p in input_dir.glob("*.json") if p.stem.isdigit()], key=lambda p: int(p.stem), reverse=True
        )
        if not json_files:
            raise CommandError(f"No JSON files found in {input_dir}")

        self.stdout.write(f"Found {len(json_files)} issue files to ingest for team {team.id}")

        asyncio.run(self._ingest(team, json_files))

    async def _ingest(self, team: Team, json_files: list[Path]):
        success = 0
        skipped = 0
        failed = 0

        for i, path in enumerate(json_files):
            try:
                issue = json.loads(path.read_text())

                title = issue.get("title", "")
                body = issue.get("body") or ""
                if not title or not body:
                    skipped += 1
                    continue

                source_id = str(issue.get("id", issue["number"]))

                await emit_signal(
                    team=team,
                    source_product="github",
                    source_type="issue",
                    source_id=source_id,
                    description=f"{title}\n{body}",
                    weight=1.0,
                    extra={k: v for k, v in issue.items() if k in EXTRA_FIELDS},
                )
                success += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to emit issue from {path.name}: {e}"))
                failed += 1

            if (i + 1) % 50 == 0:
                self.stdout.write(f"  progress: {i + 1}/{len(json_files)} ({success} ok, {skipped} skipped, {failed} failed)")

        self.stdout.write(
            self.style.SUCCESS(f"Done. {success} emitted, {skipped} skipped (no title/body), {failed} failed out of {len(json_files)} issues.")
        )
