"""hogli owners:* commands — resolve, who, unowned, lint, convert, diff-legacy."""

from __future__ import annotations

import sys
import json
import subprocess
from pathlib import Path

import click

from .conversion import Converter, parse_soft_file, write_generated_files
from .legacy_diff import diff_all, render_markdown
from .matcher import compile_pattern, normalize_path
from .resolver import OWNERS_FILENAME, PRODUCT_FILENAME, OwnersResolver
from .schema import normalize_product_owners, parse_owners_file, parse_product_yaml_as_owners


def _read_paths(paths: tuple[str, ...]) -> list[str]:
    """CLI paths, falling back to newline-delimited stdin when none are given."""
    if paths:
        return list(paths)
    if sys.stdin.isatty():
        return []
    return [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]


@click.command(name="owners:resolve", help="Resolve ownership for paths (args or newline-delimited stdin)")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON keyed by path")
@click.argument("paths", nargs=-1)
def cmd_resolve(as_json: bool, paths: tuple[str, ...]) -> None:
    resolver = OwnersResolver()
    targets = _read_paths(paths)
    result = {}
    for path in targets:
        r = resolver.resolve(path)
        result[normalize_path(path)] = {
            "owners": r.owners or [],
            "status": r.status,
            "slack": r.slack,
            "source": r.source,
        }
    if as_json:
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return
    for path, info in result.items():
        owners = ", ".join(info["owners"]) or "(unowned)"
        click.echo(f"{path}\t{owners}\t{info['status']}\t{info['slack'] or ''}")


@click.command(name="owners:who", help="Show who owns a single path")
@click.argument("path")
def cmd_who(path: str) -> None:
    r = OwnersResolver().resolve(path)
    click.echo(f"path:    {r.path}")
    if r.owners:
        click.echo(f"owners:  {', '.join(r.owners)}")
    elif r.unowned_by_design:
        click.echo("owners:  (unowned by design — explicit owners: null)")
    else:
        click.echo("owners:  (unowned)")
    click.echo(f"status:  {r.status}")
    click.echo(f"slack:   {r.slack or '(none)'}")
    if r.oncall:
        click.echo(f"oncall:  {r.oncall}")
    click.echo(f"source:  {r.source or '(none)'}")


@click.command(name="owners:unowned", help="List unowned tracked files (respecting owners: null exemptions)")
@click.argument("prefix", required=False)
def cmd_unowned(prefix: str | None) -> None:
    resolver = OwnersResolver()
    files = resolver.tracked_files(prefix)
    unowned = resolver.unowned(files)
    for path in unowned:
        click.echo(path)
    click.echo(f"\n{len(unowned)} unowned of {len(files)} tracked file(s)", err=True)


def _validate_owners_live(all_owners: set[str]) -> list[str]:
    """Validate team slugs and @handles against the GitHub org. Returns error strings."""
    from ..product.gh import get_team_slugs

    errors: list[str] = []
    teams = {o for o in all_owners if not o.startswith("@")}
    handles = {o[1:] for o in all_owners if o.startswith("@")}

    valid_slugs, slug_err = get_team_slugs()
    if valid_slugs is None:
        errors.append(f"could not validate team slugs: {slug_err}")
    else:
        for slug in sorted(teams - valid_slugs):
            errors.append(f"unknown team slug: {slug}")

    for handle in sorted(handles):
        result = subprocess.run(
            ["gh", "api", f"users/{handle}", "--jq", ".login"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(f"unknown GitHub user: @{handle}")
    return errors


def _reserved_location_error(rel: str) -> str | None:
    """Reject owners.yaml where other tooling globs every YAML in the directory:
    Actions/actionlint treat all of .github/workflows/ as workflows, and
    services/mcp generate-tools globs YAML in products/*/mcp/. Hoist ownership
    into the parent's rules instead."""
    if rel.startswith(".github/workflows/"):
        return f"{rel}: owners.yaml is not allowed under .github/workflows/ (Actions parses every YAML there as a workflow); move it to .github/owners.yaml rules"
    parts = rel.split("/")
    if parts[0] == "products" and "mcp" in parts[:-1]:
        return f"{rel}: owners.yaml is not allowed inside a products/*/mcp/ directory (mcp tooling globs every YAML there); move it to the product's product.yaml or a parent owners.yaml"
    return None


@click.command(name="owners:lint", help="Validate owners.yaml files, conflicts, dead globs, and coverage")
@click.option("--live", is_flag=True, help="Also validate team slugs and @handles against the GitHub org")
def cmd_lint(live: bool) -> None:
    resolver = OwnersResolver()
    repo_root = resolver.repo_root
    errors: list[str] = []
    warnings: list[str] = []
    all_owners: set[str] = set()

    tracked = resolver.tracked_files()
    tracked_by_dir: dict[str, list[str]] = {}
    for path in tracked:
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        tracked_by_dir.setdefault(directory, []).append(path)

    for owners_file in resolver.ownership_files():
        rel = owners_file.relative_to(repo_root).as_posix()
        directory = rel.rsplit("/", 1)[0] if "/" in rel else ""

        if owners_file.name == OWNERS_FILENAME:
            reserved_error = _reserved_location_error(rel)
            if reserved_error is not None:
                errors.append(reserved_error)

        if owners_file.name == PRODUCT_FILENAME:
            # Only flags a conflict; product.yaml owners are validated by product:lint:owners.
            if (owners_file.parent / OWNERS_FILENAME).is_file():
                errors.append(f"{directory or '<root>'}: has both product.yaml (with owners) and owners.yaml")
            parsed = parse_product_yaml_as_owners(owners_file.read_text(), path=owners_file, directory=directory)
            if parsed and parsed.owners:
                all_owners.update(normalize_product_owners(parsed.owners))
            continue

        parsed, file_errors = parse_owners_file(owners_file.read_text(), path=owners_file, directory=directory)
        for err in file_errors:
            errors.append(f"{rel}: {err}")
        if parsed is None:
            continue
        if parsed.owners:
            all_owners.update(parsed.owners)

        # Dead rule globs: a rule matching zero tracked files under its directory.
        under_dir = (
            [p for d, files in tracked_by_dir.items() if d == directory or d.startswith(directory + "/") for p in files]
            if directory
            else tracked
        )
        for rule in parsed.rules:
            all_owners.update(o for o in (rule.owners if isinstance(rule.owners, list) else []))
            matcher = compile_pattern(rule.match)
            rel_paths = (p[len(directory) + 1 :] if directory else p for p in under_dir)
            if not any(matcher.test(rp) for rp in rel_paths):
                warnings.append(f"{rel}: rule '{rule.match}' matches zero tracked files (dead glob)")

    if live:
        errors.extend(_validate_owners_live(all_owners))

    unowned = resolver.unowned(tracked)
    warnings.append(f"coverage: {len(unowned)} of {len(tracked)} tracked file(s) resolve to unowned")

    for warning in warnings:
        click.echo(f"⚠ {warning}")
    for err in errors:
        click.echo(f"✗ {err}", err=True)

    if errors:
        click.echo(f"\n✗ {len(errors)} owners.yaml error(s)", err=True)
        raise SystemExit(1)
    click.echo(f"\n✓ owners.yaml lint passed ({len(warnings)} warning(s))")


def _load_product_owners(repo_root: Path) -> dict[str, list[str]]:
    products_dir = repo_root / "products"
    result: dict[str, list[str]] = {}
    if not products_dir.is_dir():
        return result
    for entry in sorted(products_dir.iterdir()):
        product_yaml = entry / "product.yaml"
        if not entry.is_dir() or not product_yaml.is_file():
            continue
        parsed = parse_product_yaml_as_owners(
            product_yaml.read_text(), path=product_yaml, directory=f"products/{entry.name}"
        )
        if parsed is not None:
            result[entry.name] = normalize_product_owners(parsed.owners or [])
    return result


@click.command(name="owners:convert", help="Generate distributed owners.yaml from .github/CODEOWNERS-soft")
@click.option("--dry-run", is_flag=True, help="Show what would be written without writing")
def cmd_convert(dry_run: bool) -> None:
    resolver = OwnersResolver()
    repo_root = resolver.repo_root
    soft_path = repo_root / ".github" / "CODEOWNERS-soft"
    if not soft_path.is_file():
        raise click.ClickException(f"no CODEOWNERS-soft at {soft_path}")

    soft_rules = parse_soft_file(soft_path.read_text())
    converter = Converter(repo_root, _load_product_owners(repo_root))
    summary = converter.convert(soft_rules)
    written = write_generated_files(summary, repo_root, dry_run=dry_run)

    click.echo(f"{'Would write' if dry_run else 'Wrote'} {len(written)} owners.yaml file(s):")
    for rel in written:
        click.echo(f"  {rel}")
    click.echo(f"\nRedundant (covered by product.yaml): {len(summary.redundant_skips)}")
    for note in summary.redundant_skips:
        click.echo(f"  {note}")
    click.echo(f"\nNeeds decision (resolve by hand): {len(summary.needs_decision)}")
    for note in summary.needs_decision:
        click.echo(f"  {note}")
    if summary.notes:
        click.echo(f"\nNotes: {len(summary.notes)}")
        for note in summary.notes:
            click.echo(f"  {note}")


def _load_soft_text(repo_root: Path, soft_file: str | None) -> str:
    """Read CODEOWNERS-soft for the differ. The file is deleted post-migration, so
    fall back to its git history: explicit ``--soft-file`` wins, then the on-disk
    default, then ``git show HEAD:.github/CODEOWNERS-soft``."""
    if soft_file:
        return Path(soft_file).read_text()

    default = repo_root / ".github" / "CODEOWNERS-soft"
    if default.is_file():
        return default.read_text()

    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", "HEAD:.github/CODEOWNERS-soft"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout
    raise click.ClickException(
        "no CODEOWNERS-soft on disk or at HEAD:.github/CODEOWNERS-soft. "
        "Pass --soft-file PATH, or run against a ref/commit that still has it "
        "(e.g. `git show <ref>:.github/CODEOWNERS-soft > /tmp/soft && hogli owners:diff-legacy --soft-file /tmp/soft`)."
    )


@click.command(
    name="owners:diff-legacy", help="Prove owners.yaml resolution matches legacy CODEOWNERS-soft + product.yaml"
)
@click.option("--report", "report_path", type=click.Path(), help="Write the full classified list as markdown")
@click.option(
    "--soft-file",
    "soft_file",
    type=click.Path(exists=True),
    help="Path to a CODEOWNERS-soft snapshot (the file is deleted post-migration; defaults to HEAD's copy)",
)
def cmd_diff_legacy(report_path: str | None, soft_file: str | None) -> None:
    resolver = OwnersResolver()
    soft_text = _load_soft_text(resolver.repo_root, soft_file)
    report = diff_all(resolver.repo_root, soft_text, resolver)

    for klass, count in report.counts.items():
        click.echo(f"{klass.value}: {count}")

    if report_path:
        Path(report_path).write_text(render_markdown(report))
        click.echo(f"\nWrote report to {report_path}")

    if report.violates_invariants:
        click.echo("\n✗ invariant violated: ORPHANED or EXPANDED paths exist", err=True)
        raise SystemExit(1)
    click.echo("\n✓ no ORPHANED or EXPANDED paths (narrowing and newly-owned are allowed)")
