# ruff: noqa: T201 allow print statements
"""Command line entry point."""

from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path

from . import (
    __doc__ as PACKAGE_DOC,
    skill_builder,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))


def _setup_django() -> None:
    """Set up Django (needed for importing product models during build/check).

    Sets dummy values for infrastructure env vars (Redis, etc.) that the settings
    module requires at import time. The build script never connects to these services
    — it only needs the Django ORM metadata and model imports to work.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    # A build must not depend on reaching the flags endpoint. Rendering a HogQL example walks
    # `Database.create_for`, which asks posthoganalytics whether a flag is on; that call has no
    # timeout, so on a machine without egress the build sits in connect() forever with no output
    # and no error. Opting out makes `feature_enabled` answer locally instead.
    os.environ.setdefault("OPT_OUT_CAPTURE", "1")
    try:
        import django

        django.setup()
    except SystemExit as e:
        print(
            f"ERROR: Django setup called sys.exit({e.code}). "
            "This usually means a required setting (e.g. SECRET_KEY) is missing. "
            "Skill building requires a working Django environment because Jinja2 "
            "templates import Pydantic models from product code.\n"
            "Hint: set SECRET_KEY in your environment or .env file.",
            file=sys.stderr,
        )
        raise SystemExit(1) from e
    except Exception as e:
        print(
            f"WARNING: Django setup failed ({e}). Template functions that import models will not work.",
            file=sys.stderr,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m products.posthog_ai.scripts.build_skills",
        description=PACKAGE_DOC or "",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List discovered product skills without building",
    )
    parser.add_argument(
        "--lint",
        action="store_true",
        help="Validate skill sources without rendering (no Django needed)",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Scaffold a new skill directory with SKILL.md boilerplate",
    )
    parser.add_argument(
        "--product",
        help="Product name for --init (e.g. feature_flags)",
    )
    parser.add_argument(
        "--name",
        help="Skill name for --init (e.g. my-new-skill)",
    )
    parser.add_argument(
        "--j2",
        action="store_true",
        help="Create SKILL.md.j2 instead of SKILL.md (use with --init)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Build a skill and sync it to .agents/skills/ for local testing",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove a previously synced skill from .agents/skills/ (use with --sync)",
    )
    return parser


def _run_init(builder: skill_builder.SkillBuilder, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not args.product or not args.name:
        parser.error("--init requires --product and --name")
    try:
        skill_file = builder.init_skill(args.product, args.name, template=args.j2)
        print(f"Created {skill_file.relative_to(REPO_ROOT)}")
    except (FileNotFoundError, FileExistsError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _run_sync(builder: skill_builder.SkillBuilder, args: argparse.Namespace) -> None:
    if not args.name:
        builder.list_skills()
        print("\nUsage: hogli sync:skill -- --name <skill-name>")
        return
    if args.clean:
        builder.unsync_skill(args.name)
        return
    _setup_django()
    try:
        target = builder.sync_skill(args.name)
        print(f"Synced skill to {target.relative_to(REPO_ROOT)}")
        print(f"  Available via .claude/skills/{target.name}/ for Claude Code")
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _run_build(builder: skill_builder.SkillBuilder) -> None:
    _setup_django()
    manifest = builder.build_all()
    if not manifest.resources:
        print("No product skills found in products/*/skills/.")
        return
    zip_path = builder._zip_skills_dist()
    print(f"Built {len(manifest.resources)} skill(s) → {zip_path.relative_to(REPO_ROOT)}")
    for r in manifest.resources:
        print(f"  {r.name:<40} source={r.source}")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    products_dir = REPO_ROOT / "products"
    output_dir = REPO_ROOT / "products" / "posthog_ai"
    builder = skill_builder.SkillBuilder(REPO_ROOT, products_dir, output_dir)

    if args.init:
        _run_init(builder, args, parser)
    elif args.lint:
        if not builder.lint_all():
            sys.exit(1)
    elif args.sync:
        _run_sync(builder, args)
    elif args.list:
        builder.list_skills()
    else:
        _run_build(builder)
