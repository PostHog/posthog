"""The ``owners`` CLI: resolve, who, census, codeowners, unowned, lint, fmt.

Each command is a plain click command named ``owners:<name>``, so a host CLI can register it
directly. The ``owners`` console script groups the same commands without the prefix.
"""

from __future__ import annotations

import sys
import json
from collections import defaultdict
from pathlib import Path
from typing import cast

import click

from .census import census
from .codeowners import package_dirs_from, project
from .github import GitHubLookupError, GitHubOrg
from .matcher import compile_pattern, normalize_path
from .resolver import (
    OWNERS_FILENAME,
    PRODUCT_FILENAME,
    OwnersResolver,
    Purpose,
    RepoRootNotFound,
    read_stdin_paths,
    resolution_to_wire,
)
from .schema import RepoSettings, is_simple_owners_file, normalize_product_owners

# GitHub Actions parses every YAML file under this directory as a workflow, in any repo.
BUILTIN_RESERVED_DIRS = (".github/workflows/**",)

repo_root_option = click.option(
    "--repo-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory that holds the ownership files. Default: the enclosing git worktree.",
)

org_option = click.option(
    "--org",
    default=None,
    help="GitHub organization of the team slugs. Default: `github_org` in the root owners.yaml.",
)


def _resolver(repo_root: Path | None, purpose: Purpose = "slack") -> OwnersResolver:
    try:
        return OwnersResolver(repo_root=repo_root, purpose=purpose)
    except RepoRootNotFound as exc:
        raise click.ClickException(str(exc)) from exc


def _github_org(org: str | None, settings: RepoSettings) -> str:
    resolved = org or settings.github_org
    if not resolved:
        raise click.ClickException("no GitHub organization: set `github_org` in the root owners.yaml or pass --org")
    return resolved


def _read_paths(paths: tuple[str, ...]) -> list[str]:
    """CLI paths, falling back to newline-delimited stdin when none are given."""
    if paths:
        return list(paths)
    if sys.stdin.isatty():
        return []
    return read_stdin_paths()


@click.command(name="owners:resolve", help="Resolve ownership for paths (args or newline-delimited stdin)")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON keyed by path")
@click.option(
    "--purpose",
    type=click.Choice(["slack", "notifications"]),
    default="slack",
    help="Which team channel `slack` resolves to: where people are, or where automation posts",
)
@repo_root_option
@click.argument("paths", nargs=-1)
def cmd_resolve(as_json: bool, purpose: str, repo_root: Path | None, paths: tuple[str, ...]) -> None:
    resolver = _resolver(repo_root, cast(Purpose, purpose))
    targets = _read_paths(paths)
    result = {normalize_path(path): resolution_to_wire(resolver.resolve(path)) for path in targets}
    if as_json:
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return
    for path, info in result.items():
        owners = ", ".join(info["owners"]) or "(unowned)"
        click.echo(f"{path}\t{owners}\t{info['status']}\t{info['slack'] or ''}")


@click.command(name="owners:who", help="Show who owns a single path")
@repo_root_option
@click.argument("path")
def cmd_who(repo_root: Path | None, path: str) -> None:
    r = _resolver(repo_root).resolve(path)
    click.echo(f"path:    {r.path}")
    if r.owners:
        click.echo(f"owners:  {', '.join(r.owners)}")
    elif r.unowned_by_design:
        click.echo("owners:  (unowned by design — explicit owners: null)")
    else:
        click.echo("owners:  (unowned)")
    click.echo(f"status:  {r.status}")
    click.echo(f"slack:   {r.slack or '(none)'}")
    click.echo(f"source:  {r.source or '(none)'}")


@click.command(name="owners:census", help="Count test files per owning team")
@click.option("--json", "as_json", is_flag=True, help="Emit a JSON list of per-team counts")
@repo_root_option
@click.argument("prefix", required=False)
def cmd_census(as_json: bool, repo_root: Path | None, prefix: str | None) -> None:
    resolver = _resolver(repo_root)
    rows = census(resolver.tracked_files(prefix), resolver.repo_root)
    if as_json:
        click.echo(json.dumps([row.as_payload() for row in rows], indent=2))
        return
    for row in rows:
        click.echo(
            f"{row.test_file_count:6d}  {row.pytest_file_count:6d} py  {row.jest_file_count:6d} js  {row.owner_team}"
        )
    click.echo(f"\n{sum(r.test_file_count for r in rows)} test file(s) across {len(rows)} team(s)", err=True)


@click.command(name="owners:codeowners", help="Emit a CODEOWNERS projection of test-file ownership")
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True),
    help="Write to this file instead of stdout",
)
@org_option
@repo_root_option
def cmd_codeowners(output: str | None, org: str | None, repo_root: Path | None) -> None:
    resolver = _resolver(repo_root)
    settings = resolver.settings()
    tracked = resolver.tracked_files()
    projection = project(
        tracked,
        resolver,
        org=_github_org(org, settings),
        package_dirs=package_dirs_from(tracked),
        settings=settings.codeowners,
    )
    if output:
        Path(output).write_text(projection.render())
    else:
        click.echo(projection.render(), nl=False)
    click.echo(
        f"{len(projection.lines)} rule(s) covering {projection.owned_file_count} test file(s); "
        f"{projection.unowned_file_count} unowned, {len(projection.ambiguous_spellings)} ambiguous spelling(s) dropped",
        err=True,
    )


@click.command(name="owners:unowned", help="List unowned tracked files (respecting owners: null exemptions)")
@repo_root_option
@click.argument("prefix", required=False)
def cmd_unowned(repo_root: Path | None, prefix: str | None) -> None:
    resolver = _resolver(repo_root)
    files = resolver.tracked_files(prefix)
    unowned = resolver.unowned(files)
    for path in unowned:
        click.echo(path)
    click.echo(f"\n{len(unowned)} unowned of {len(files)} tracked file(s)", err=True)


def _validate_owners_live(all_owners: set[str], github: GitHubOrg) -> list[str]:
    """Validate team slugs and @handles against the GitHub org. Returns error strings."""
    errors: list[str] = []
    teams = {o for o in all_owners if not o.startswith("@")}
    handles = {o[1:] for o in all_owners if o.startswith("@")}

    try:
        valid_slugs = github.team_slugs()
    except GitHubLookupError as exc:
        return [f"could not validate team slugs: {exc}"]
    for slug in sorted(teams - valid_slugs):
        errors.append(f"unknown team slug: {slug}")

    for handle in sorted(handles):
        # A review request to someone outside the org fails, so account existence is not enough.
        try:
            is_member = github.is_member(handle)
        except GitHubLookupError as exc:
            errors.append(f"could not validate @{handle}: {exc}")
            continue
        if not is_member:
            errors.append(f"not a {github.org} org member (unassignable): @{handle}")
    return errors


def _reserved_location_error(rel: str, reserved_dirs: tuple[str, ...]) -> str | None:
    """Reject an owners.yaml where other tooling reads every YAML file in the directory. Hoist its
    ownership into a parent's rules instead."""
    for pattern in (*BUILTIN_RESERVED_DIRS, *reserved_dirs):
        if compile_pattern(pattern).test(rel):
            return (
                f"{rel}: owners.yaml is not allowed here, because the reserved pattern '{pattern}' matches it"
                " (other tooling reads every YAML file there); move the ownership into a parent owners.yaml"
            )
    return None


def _consolidation_suggestions(owners_dirs: dict[str, bool], threshold: int = 3) -> list[tuple[str, int]]:
    """Advisory: directories that could fold a cluster of single-purpose owners.yaml
    files into one anchored ``rules:`` block.

    ``owners_dirs`` maps each owners.yaml's directory ("" = repo root) to whether it
    is simple (see ``is_simple_owners_file``). A directory D is suggested when at least
    ``threshold`` simple files sit strictly below it with no non-simple file on the
    path between (a non-simple file keeps nearest-wins correct, so its subtree stays
    put), and those files span ≥2 of D's immediate children — so D is their genuine
    branch point, not a passthrough ancestor. Only the deepest branch point per
    cluster is reported, so nested/ancestor dirs don't double-report."""

    def is_ancestor(ancestor: str, descendant: str) -> bool:
        if ancestor == descendant:
            return False
        return descendant.startswith(ancestor + "/") if ancestor else True

    non_simple = [d for d, simple in owners_dirs.items() if not simple]
    simple = [d for d, is_simple in owners_dirs.items() if is_simple]

    candidate_dirs: set[str] = {""}
    for f in simple:
        parts = f.split("/")
        for i in range(1, len(parts)):
            candidate_dirs.add("/".join(parts[:i]))

    counts: dict[str, int] = {}
    for directory in candidate_dirs:
        counted = [
            f
            for f in simple
            if is_ancestor(directory, f)
            and not any(is_ancestor(directory, ns) and is_ancestor(ns, f) for ns in non_simple)
        ]
        if len(counted) < threshold:
            continue
        children = {(f[len(directory) + 1 :] if directory else f).split("/", 1)[0] for f in counted}
        if len(children) < 2:
            continue
        counts[directory] = len(counted)

    return sorted(
        (directory, count)
        for directory, count in counts.items()
        if not any(is_ancestor(directory, other) for other in counts if other != directory)
    )


def _live_scope(owners_by_file: dict[str, set[str]], paths: tuple[str, ...]) -> set[str]:
    """Owners to validate: all of them, or only those declared in PATHS.

    Callers scope this to the diff's ownership files. Unscoped, one stale slug
    fails every PR that touches any owners.yaml, none of which can fix it. A
    path with nothing to contribute (deleted, not an ownership file) just misses.
    """
    if not paths:
        return {owner for owners in owners_by_file.values() for owner in owners}
    wanted = {normalize_path(p) for p in paths}
    return {owner for rel, owners in owners_by_file.items() if rel in wanted for owner in owners}


@click.command(name="owners:lint", help="Validate owners.yaml files, conflicts, dead globs, and coverage")
@click.option("--live", is_flag=True, help="Also validate team slugs and @handles against the GitHub org")
@org_option
@repo_root_option
@click.argument("paths", nargs=-1)
def cmd_lint(live: bool, org: str | None, repo_root: Path | None, paths: tuple[str, ...]) -> None:
    resolver = _resolver(repo_root)
    repo_root = resolver.repo_root
    settings = resolver.settings()
    errors: list[str] = []
    warnings: list[str] = []
    owners_by_file: defaultdict[str, set[str]] = defaultdict(set)
    owners_dirs: dict[str, bool] = {}

    tracked = resolver.tracked_files()
    tracked_by_dir: dict[str, list[str]] = {}
    for path in tracked:
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        tracked_by_dir.setdefault(directory, []).append(path)

    entries = resolver.parsed_ownership_files()  # the single parse pass
    owners_yaml_dirs = {e.rel_dir for e in entries if e.name == OWNERS_FILENAME}

    for entry in entries:
        rel = entry.path.relative_to(repo_root).as_posix()
        directory = entry.rel_dir
        parsed = entry.parsed

        if entry.name == OWNERS_FILENAME:
            reserved_error = _reserved_location_error(rel, settings.reserved_dirs)
            if reserved_error is not None:
                errors.append(reserved_error)

        if entry.name == PRODUCT_FILENAME:
            # Only flags a conflict. A host that scaffolds product.yaml validates its owners itself.
            if directory in owners_yaml_dirs:
                errors.append(f"{directory or '<root>'}: has both product.yaml (with owners) and owners.yaml")
            if parsed and parsed.owners:
                owners_by_file[rel].update(normalize_product_owners(parsed.owners))
            continue

        for err in entry.errors:
            errors.append(f"{rel}: {err}")
        owners_dirs[directory] = is_simple_owners_file(parsed)
        if parsed is None:
            continue
        if parsed.owners:
            owners_by_file[rel].update(parsed.owners)

        if not parsed.rules:
            continue

        # Dead rule globs: a rule matching zero tracked files under its directory.
        under_dir = (
            [p for d, files in tracked_by_dir.items() if d == directory or d.startswith(directory + "/") for p in files]
            if directory
            else tracked
        )
        # Slice paths relative to the file's directory once, not per rule.
        rel_paths = [p[len(directory) + 1 :] for p in under_dir] if directory else under_dir
        for rule in parsed.rules:
            owners_by_file[rel].update(rule.owners if isinstance(rule.owners, list) else [])
            matcher = compile_pattern(rule.match)
            if not any(matcher.test(rp) for rp in rel_paths):
                warnings.append(f"{rel}: rule '{rule.match}' matches zero tracked files (dead glob)")

    if live:
        github = GitHubOrg(_github_org(org, settings))
        errors.extend(_validate_owners_live(_live_scope(owners_by_file, paths), github))

    unowned = resolver.unowned(tracked)
    warnings.append(f"coverage: {len(unowned)} of {len(tracked)} tracked file(s) resolve to unowned")

    for warning in warnings:
        click.echo(f"⚠ {warning}")

    # Advisory only — never affects the exit code. Points out dirs where a cluster
    # of single-purpose owners.yaml files could fold into one anchored rules block.
    for directory, count in _consolidation_suggestions(owners_dirs):
        target = f"{directory}/{OWNERS_FILENAME}" if directory else OWNERS_FILENAME
        where = directory or "<repo root>"
        click.echo(
            f"suggestion: {where} has {count} single-purpose owners.yaml files below it"
            f" — consider folding them into {target} rules"
        )

    for err in errors:
        click.echo(f"✗ {err}", err=True)

    if errors:
        click.echo(f"\n✗ {len(errors)} owners.yaml error(s)", err=True)
        raise SystemExit(1)
    click.echo(f"\n✓ owners.yaml lint passed ({len(warnings)} warning(s))")


@click.command(
    name="owners:fmt",
    help="Dry-run oracle: show how the current owners.yaml layout differs from the canonical placement",
)
@repo_root_option
def cmd_fmt(repo_root: Path | None) -> None:
    from .fmt import ALPHA, GAMMA, MAX_RULES, CanonicalPlacer  # noqa: PLC0415 — keeps the DP off the CLI import path

    placer = CanonicalPlacer(_resolver(repo_root))
    plan = placer.build()

    if plan.is_canonical:
        click.echo(f"✓ layout is canonical (cost {plan.canonical_cost})")
        click.echo("✓ canonical layout resolves identically")
        return

    if plan.creations:
        click.echo(f"Create ({len(plan.creations)}):")
        for path in plan.creations:
            click.echo(f"    + {path}")
    if plan.deletions:
        click.echo(f"Delete ({len(plan.deletions)}) — statements fold into an ancestor:")
        for path in plan.deletions:
            click.echo(f"    - {path}")
    if plan.additions:
        click.echo("Add rules:")
        for path in sorted(plan.additions):
            for line in plan.additions[path]:
                click.echo(f"    {path}: {line}")

    click.echo(f"\ncost: current {plan.current_cost} → canonical {plan.canonical_cost}")
    click.echo(f"(constants: ALPHA={ALPHA}, GAMMA={GAMMA}, MAX_RULES={MAX_RULES})")
    click.echo("✓ canonical layout resolves identically")
    click.echo("\nnote: owners:fmt is a read-only oracle — it never writes. Reflows are deliberate human decisions.")


@click.group()
@click.version_option(package_name="posthog-owners")
def main() -> None:
    """Resolve, lint, and format distributed owners.yaml ownership files."""


main.add_command(cmd_census, name="census")
main.add_command(cmd_codeowners, name="codeowners")
main.add_command(cmd_resolve, name="resolve")
main.add_command(cmd_who, name="who")
main.add_command(cmd_unowned, name="unowned")
main.add_command(cmd_lint, name="lint")
main.add_command(cmd_fmt, name="fmt")
