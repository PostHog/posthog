"""hogli lint:migration-deletions — fail when a PR deletes a historical Django migration.

Reads removed/renamed paths from stdin (the repo-checks CI job feeds them
from the GitHub PR-files API) and fails on any Django migration the allowlist doesn't
acknowledge. Those paths are removed relative to the PR base, so each already-existing
migration among them is historical. See _GUIDANCE and
docs/published/handbook/engineering/safe-django-migrations.md for the why.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath

import click
from hogli.manifest import REPO_ROOT

ALLOWLIST_PATH = REPO_ROOT / ".github" / "scripts" / "migration-deletion-allowlist.txt"

# ClickHouse and async migrations are separate systems, excluded by grandparent dir name.
_NON_DJANGO_PARENTS = {"clickhouse", "async_migrations"}

_IN_GH_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"

_GUIDANCE = """\
Deleting a migration that exists on master does NOT undo a schema change. The table
and its constraints stay in every database where the migration ran, fresh databases
never recreate them, and the Migration Risk Analysis job re-flags it as a phantom new
migration on every open PR that predates the deletion.

To retire a model/table instead:
  1. Remove all usage and the model class. Run makemigrations, then wrap the generated
     DeleteModel in migrations.SeparateDatabaseAndState(state_operations=[...]) so it
     changes Django state only. KEEP this file. Keep the app in INSTALLED_APPS.
  2. Deploy and wait at least one full deploy cycle.
  3. Optionally DROP TABLE later in a NEW RunSQL migration — never by deleting old files.

Full guide: docs/published/handbook/engineering/safe-django-migrations.md
("Dropping Tables", "Removing a whole product or app").

If this deletion is genuinely intentional and reviewed (a product/app move, a revert,
or a squash), acknowledge it by adding the path(s) to
.github/scripts/migration-deletion-allowlist.txt — never by disabling this guard."""


def is_django_migration(path: str) -> bool:
    """True for a numbered Django migration file, e.g. posthog/migrations/0001_initial.py.

    Require the NNNN_ prefix: it excludes __init__.py and, crucially, the standalone data
    scripts that also live in a migrations/ dir (e.g. posthog/rbac/migrations/rbac_*.py),
    which are not Django ORM migrations. Also excludes the ClickHouse/async systems.
    """
    p = PurePosixPath(path)
    if p.parent.name != "migrations" or p.suffix != ".py" or not p.name[:1].isdigit():
        return False
    return p.parent.parent.name not in _NON_DJANGO_PARENTS


def load_allowlist(allowlist_path: Path) -> list[str]:
    """Allowlist entries (one path per line; '#' comments, blanks, and a missing file ignored)."""
    if not allowlist_path.exists():
        return []
    entries = []
    for line in allowlist_path.read_text().splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            entries.append(entry)
    return entries


def is_allowlisted(path: str, allowlist: list[str]) -> bool:
    """True if path matches an allowlist entry exactly, or sits under a directory entry
    (trailing slash optional, so `products/x/migrations` and `.../migrations/` both work)."""
    for entry in allowlist:
        prefix = entry.rstrip("/")
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def guarded_deletions(paths: list[str], allowlist: list[str]) -> list[str]:
    """The subset of deleted paths that are Django migrations and not allowlisted."""
    return [p for p in paths if is_django_migration(p) and not is_allowlisted(p, allowlist)]


@click.command(name="lint:migration-deletions", help="Block deleting historical Django migration files")
def cmd_lint_migration_deletions() -> None:
    """Read removed file paths from stdin and fail on any historical Django migration."""
    removed = sys.stdin.read().splitlines()
    violations = guarded_deletions(removed, load_allowlist(ALLOWLIST_PATH))

    if not violations:
        click.echo("No historical migration files deleted.")
        return

    if _IN_GH_ACTIONS:
        for path in violations:
            click.echo(
                f"::error file={path} title=lint:migration-deletions::Deleting a historical Django migration is not allowed (see safe-django-migrations.md)"
            )
    click.echo("\nERROR: refusing to delete historical Django migration file(s):\n", err=True)
    for path in violations:
        click.echo(f"  - {path}", err=True)
    click.echo(f"\n{_GUIDANCE}", err=True)
    raise SystemExit(1)
