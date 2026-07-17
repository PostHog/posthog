from __future__ import annotations

from pathlib import Path

import pytest

import hogli_commands.migration_deletions as md
from click.testing import CliRunner


@pytest.mark.parametrize(
    "path,expected",
    [
        ("posthog/migrations/0001_initial.py", True),
        ("ee/migrations/0042_thing.py", True),
        ("products/tasks/backend/migrations/0003_x.py", True),
        ("posthog/session/migrations/0001_initial.py", True),  # real Django sub-package app
        ("posthog/migrations/__init__.py", False),
        ("posthog/migrations/manual_fix.py", False),  # non-numbered -> not a flagged migration
        ("posthog/rbac/migrations/rbac_team_migration.py", False),  # standalone RBAC data script, not ORM
        ("posthog/clickhouse/migrations/0099_x.py", False),
        ("posthog/async_migrations/migrations/0005_y.py", False),
        ("posthog/migrations/0001_initial.txt", False),
        ("products/tasks/backend/views.py", False),
    ],
)
def test_is_django_migration(path: str, expected: bool) -> None:
    assert md.is_django_migration(path) is expected


def test_load_allowlist_ignores_comments_and_blanks(tmp_path: Path) -> None:
    f = tmp_path / "allow.txt"
    f.write_text(
        "# header\n\nposthog/migrations/0500_oops.py   # trailing comment\n  products/old/backend/migrations/  \n"
    )
    assert md.load_allowlist(f) == ["posthog/migrations/0500_oops.py", "products/old/backend/migrations/"]


def test_load_allowlist_missing_file_is_empty(tmp_path: Path) -> None:
    assert md.load_allowlist(tmp_path / "nope.txt") == []


@pytest.mark.parametrize(
    "path,allowlist,expected",
    [
        ("posthog/migrations/0500_oops.py", ["posthog/migrations/0500_oops.py"], True),
        ("products/old/backend/migrations/0001_initial.py", ["products/old/backend/migrations/"], True),
        (
            "products/old/backend/migrations/0001_initial.py",
            ["products/old/backend/migrations"],
            True,
        ),  # trailing slash optional
        ("products/old_v2/backend/migrations/0001_initial.py", ["products/old/backend/migrations/"], False),
        ("posthog/migrations/0500_oops.py", [], False),
    ],
)
def test_is_allowlisted(path: str, allowlist: list[str], expected: bool) -> None:
    assert md.is_allowlisted(path, allowlist) is expected


def test_guarded_deletions_filters_and_respects_allowlist() -> None:
    paths = [
        "posthog/migrations/0001_initial.py",
        "posthog/migrations/__init__.py",
        "posthog/clickhouse/migrations/0099_x.py",
        "products/old/backend/migrations/0001_x.py",
        "frontend/app.ts",
    ]
    assert md.guarded_deletions(paths, ["products/old/backend/migrations/"]) == ["posthog/migrations/0001_initial.py"]


@pytest.mark.parametrize(
    "stdin,allowlist,expected_exit",
    [
        ("posthog/migrations/0001_initial.py\nfrontend/x.ts\n", "", 1),  # historical deletion -> block
        ("posthog/migrations/__init__.py\nfrontend/app.ts\n", "", 0),  # only non-migrations -> pass
        # historical migration deleted but acknowledged in the allowlist -> pass
        ("products/old/backend/migrations/0001_x.py\n", "products/old/backend/migrations/\n", 0),
    ],
)
def test_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stdin: str, allowlist: str, expected_exit: int
) -> None:
    allow = tmp_path / "allow.txt"
    allow.write_text(allowlist)
    monkeypatch.setattr(md, "ALLOWLIST_PATH", allow)
    result = CliRunner().invoke(md.cmd_lint_migration_deletions, input=stdin)
    # A crash also exits non-zero — assert the exit is a real verdict, not a trapped exception.
    assert not isinstance(result.exception, Exception)
    assert result.exit_code == expected_exit
