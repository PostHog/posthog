import json
import time
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import requests

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "github_issues"

PER_PAGE = 100


def _token_from_gh_cli() -> str | None:
    """Try to grab a token from the gh CLI if it's installed and authed."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def resolve_token(explicit_token: str | None, stdout) -> str | None:
    """Resolve a GitHub token: explicit flag > gh CLI > None (unauthenticated)."""
    if explicit_token:
        return explicit_token

    stdout.write("No --token provided, trying `gh auth token`...")
    token = _token_from_gh_cli()
    if token:
        stdout.write("  ✓ Got token from gh CLI\n")
        return token

    stdout.write("  ✗ gh CLI not available or not logged in\n")
    stdout.write("  Continuing without auth (60 requests/hr limit)\n")
    return None


class Command(BaseCommand):
    help = "Download every open issue from a GitHub repo as individual JSON files"

    def add_arguments(self, parser):
        parser.add_argument(
            "repo",
            type=str,
            nargs="?",
            default="posthog/posthog",
            help="GitHub repo in owner/name format (default: posthog/posthog)",
        )
        parser.add_argument(
            "--token",
            type=str,
            default=None,
            help="GitHub personal access token. If omitted, tries `gh auth token` then device login flow.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max number of issues to download (default: all)",
        )
        parser.add_argument(
            "--label",
            type=str,
            action="append",
            default=None,
            help="Filter by label (can be specified multiple times, default: bug). Pass --label '' to disable.",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help=f"Output directory (default: {OUTPUT_BASE}/<owner>/<repo>)",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        repo = options["repo"]
        if "/" not in repo or len(repo.split("/")) != 2:
            raise CommandError(f"Invalid repo format: {repo}. Expected owner/name (e.g. posthog/posthog)")

        output_dir = Path(options["output_dir"]) if options["output_dir"] else OUTPUT_BASE / repo
        output_dir.mkdir(parents=True, exist_ok=True)

        api_url = f"https://api.github.com/repos/{repo}/issues"

        limit = options["limit"]
        token = resolve_token(options["token"], self.stdout)

        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        page = 1
        total = 0

        while True:
            params = {
                "state": "open",
                "per_page": PER_PAGE,
                "page": page,
                "sort": "created",
                "direction": "desc",
                # pull requests show up in the issues endpoint; filtered out below
            }

            raw_labels = options["label"] if options["label"] is not None else ["bug"]
            labels = [lbl for lbl in raw_labels if lbl]
            if labels:
                params["labels"] = ",".join(labels)

            self.stdout.write(f"Fetching page {page}...")
            resp = requests.get(api_url, headers=headers, params=params, timeout=30)

            # Handle rate limiting
            if resp.status_code == 403 or resp.status_code == 429:
                reset_ts = resp.headers.get("X-RateLimit-Reset")
                if reset_ts:
                    wait = max(int(reset_ts) - int(time.time()), 1) + 5
                else:
                    wait = 60
                self.stdout.write(self.style.WARNING(f"Rate limited. Sleeping {wait}s..."))
                time.sleep(wait)
                continue  # retry same page

            resp.raise_for_status()
            issues = resp.json()

            if not issues:
                break

            for issue in issues:
                # Skip pull requests (they show up in the issues endpoint)
                if "pull_request" in issue:
                    continue

                issue_number = issue["number"]
                filepath = output_dir / f"{issue_number}.json"
                filepath.write_text(json.dumps(issue, indent=2, ensure_ascii=False))
                total += 1

                if limit and total >= limit:
                    break

            self.stdout.write(f"  saved {len(issues)} items from page {page} ({total} issues so far)")

            if limit and total >= limit:
                break

            # Respect rate limits proactively: if remaining is low, sleep
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining is not None and int(remaining) < 10:
                reset_ts = resp.headers.get("X-RateLimit-Reset")
                if reset_ts:
                    wait = max(int(reset_ts) - int(time.time()), 1) + 5
                else:
                    wait = 60
                self.stdout.write(self.style.WARNING(f"Rate limit low ({remaining} left). Sleeping {wait}s..."))
                time.sleep(wait)

            # If we got fewer than PER_PAGE results, we're on the last page
            if len(issues) < PER_PAGE:
                break

            page += 1

        self.stdout.write(self.style.SUCCESS(f"Done. {total} open issues saved to {output_dir}"))
