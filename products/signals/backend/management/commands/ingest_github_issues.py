import json
import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.signals.backend.api import emit_signal

DEFAULT_INPUT_DIR = Path(__file__).resolve().parent.parent.parent / "github_issues" / "posthog" / "posthog"


def _extract_repo(issue: dict) -> str:
    """Extract owner/repo from the issue's html_url or repository_url."""
    html_url = issue.get("html_url", "")
    # html_url looks like https://github.com/posthog/posthog/issues/12345
    parts = html_url.split("/")
    try:
        idx = parts.index("github.com")
        return f"{parts[idx + 1]}/{parts[idx + 2]}"
    except (ValueError, IndexError):
        repo_url = issue.get("repository_url", "")
        # repository_url looks like https://api.github.com/repos/posthog/posthog
        return "/".join(repo_url.rstrip("/").split("/")[-2:])


def _build_description(issue: dict) -> str:
    """Build a human-readable description from a GitHub issue for embedding."""
    title = issue.get("title", "")
    body = (issue.get("body") or "")[:6000]
    labels = ", ".join(lbl["name"] for lbl in issue.get("labels", []) if isinstance(lbl, dict))

    parts = [f"GitHub Issue #{issue['number']}: {title}"]
    if labels:
        parts.append(f"Labels: {labels}")
    if body:
        parts.append(f"\n{body}")
    return "\n".join(parts)


def _build_extra(issue: dict) -> dict:
    """Extract useful metadata into the extra dict."""
    return {
        "url": issue.get("html_url", ""),
        "author": issue.get("user", {}).get("login", ""),
        "labels": [lbl["name"] for lbl in issue.get("labels", []) if isinstance(lbl, dict)],
        "comments": issue.get("comments", 0),
        "created_at": issue.get("created_at", ""),
        "updated_at": issue.get("updated_at", ""),
    }


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
        parser.add_argument(
            "--weight",
            type=float,
            default=0.3,
            help="Signal weight for each issue (default: 0.3)",
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

        json_files = sorted(input_dir.glob("*.json"), key=lambda p: int(p.stem), reverse=True)
        if not json_files:
            raise CommandError(f"No JSON files found in {input_dir}")

        self.stdout.write(f"Found {len(json_files)} issue files to ingest for team {team.id}")

        asyncio.run(self._ingest(team, json_files, options["weight"]))

    async def _ingest(self, team: Team, json_files: list[Path], weight: float):
        success = 0
        failed = 0

        for i, path in enumerate(json_files):
            try:
                issue = json.loads(path.read_text())
                repo = _extract_repo(issue)
                source_id = f"{repo}#{issue['number']}"
                await emit_signal(
                    team=team,
                    source_product="github",
                    source_type="open_issue",
                    source_id=source_id,
                    description=_build_description(issue),
                    weight=weight,
                    extra=_build_extra(issue),
                )
                success += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to emit issue from {path.name}: {e}"))
                failed += 1

            if (i + 1) % 50 == 0:
                self.stdout.write(f"  progress: {i + 1}/{len(json_files)} ({success} ok, {failed} failed)")

        self.stdout.write(
            self.style.SUCCESS(f"Done. {success} signals emitted, {failed} failed out of {len(json_files)} issues.")
        )
