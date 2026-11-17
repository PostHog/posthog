"""Product lint runner."""

from __future__ import annotations

import os
from pathlib import Path

import click

from .checks import CHECKS, CheckContext, ProductYamlOwnersCheck, has_contracts_module
from .paths import PRODUCTS_DIR, backend_product_dirs, load_structure

_IN_GH_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def _gh_annotation(level: str, product: str, check_label: str, message: str, file: str | None = None) -> None:
    if _IN_GH_ACTIONS:
        file_part = f" file={file}" if file else ""
        click.echo(f"::{level}{file_part} title=product:lint ({product} / {check_label})::{message}")


def lint_product(name: str, verbose: bool = True, structure: dict | None = None) -> list[str]:
    """
    Lint a product's structure. Returns list of issues found.

    Runs in two modes based on whether the product has backend/facade/contracts.py:
      strict  — all structure rules enforced
      lenient — subset of rules enforced (see product_structure.yaml)

    The boundaries between products are hoglint's (`hoglint check`), not this lint's.

    Pass structure= to avoid re-parsing product_structure.yaml on every call (useful in --all mode).
    """
    product_dir = PRODUCTS_DIR / name
    backend_dir = product_dir / "backend"

    if not product_dir.exists():
        raise click.ClickException(f"Product '{name}' not found at {product_dir}")

    strict = has_contracts_module(backend_dir)
    mode = "strict" if strict else "lenient"

    if verbose:
        click.echo(
            f"  mode: {mode}"
            + (" (has backend/facade/contracts.py)" if strict else " (no backend/facade/contracts.py)")
        )

    ctx = CheckContext(
        name=name,
        product_dir=product_dir,
        backend_dir=backend_dir,
        has_facade_contracts=strict,
        structure=structure or load_structure(),
    )

    issues: list[str] = []
    for check in CHECKS:
        if not check.should_run(ctx):
            continue
        if verbose:
            click.echo(f"  {check.label}...")
        result = check.run(ctx)
        if result.skip:
            continue
        if verbose:
            for line in result.lines:
                click.echo(f"    {line}")
        issues.extend(result.issues)
        for issue in result.issues:
            _gh_annotation("error", name, check.label, issue, file=result.file)
        for warning in result.warnings:
            _gh_annotation("warning", name, check.label, warning, file=result.file)

    return issues


def lint_all_products() -> None:
    product_dirs = backend_product_dirs()

    strict = [d.name for d in product_dirs if has_contracts_module(d / "backend")]
    lenient = [d.name for d in product_dirs if not has_contracts_module(d / "backend")]

    click.echo(f"Linting {len(product_dirs)} products ({len(strict)} strict, {len(lenient)} lenient)")
    click.echo(
        "Checks: product.yaml, required root files, backend package marker, package.json scripts, "
        "misplaced files (strict), file/folder conflicts, test file coverage, system checks\n"
    )

    structure = load_structure()

    failed: list[str] = []
    for product_dir in product_dirs:
        click.echo(f"─ {product_dir.name}")
        issues = lint_product(product_dir.name, verbose=True, structure=structure)
        if issues:
            failed.append(product_dir.name)
        click.echo("")

    if failed:
        click.echo(f"✗ {len(failed)} product(s) failed: {', '.join(failed)}")
        raise SystemExit(1)

    click.echo(f"✓ All {len(product_dirs)} products passed")


def lint_owners(names: list[str] | None = None) -> None:
    """Validate product.yaml ``owners:`` against repo-collaborator GitHub teams.

    With ``names`` empty/None, sweeps every product (local convenience). In CI
    the call site passes the list of products whose product.yaml actually
    changed, so pre-existing rot elsewhere doesn't block unrelated PRs.

    Separated from ``lint_all_products`` because it makes a GitHub API call —
    wired into CI behind a paths filter so it only runs when a product.yaml
    changes.
    """
    if names:
        targets: list[Path] = []
        for name in names:
            d = PRODUCTS_DIR / name
            if not d.is_dir():
                click.echo(f"⚠ skipping '{name}': not a product directory")
                continue
            targets.append(d)
        # If the caller passed names but none resolved, treat it as an error —
        # otherwise an unexpected slug from CI's sed/xargs pipeline would slip
        # through as a silent green ("✓ All 0 product owners are valid").
        if not targets:
            click.echo("✗ None of the provided names matched a product directory — nothing validated")
            raise SystemExit(1)
    else:
        targets = sorted(
            d
            for d in PRODUCTS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith((".", "_")) and (d / "__init__.py").exists()
        )

    check = ProductYamlOwnersCheck()
    structure = load_structure()
    failed: list[str] = []

    scope = "all products" if not names else f"{len(targets)} changed product(s)"
    click.echo(f"Validating product.yaml owners across {scope} against PostHog/posthog teams\n")

    for product_dir in targets:
        ctx = CheckContext(
            name=product_dir.name,
            product_dir=product_dir,
            backend_dir=product_dir / "backend",
            has_facade_contracts=has_contracts_module(product_dir / "backend"),
            structure=structure,
        )
        result = check.run(ctx)
        if result.skip:
            continue
        if result.issues:
            failed.append(product_dir.name)
            click.echo(f"─ {product_dir.name}")
            for line in result.lines:
                click.echo(f"    {line}")
            for issue in result.issues:
                _gh_annotation("error", product_dir.name, check.label, issue, file=result.file)

    click.echo("")
    if failed:
        click.echo(f"✗ {len(failed)} product(s) failed owner validation: {', '.join(failed)}")
        raise SystemExit(1)

    click.echo(f"✓ All {len(targets)} product owners are valid PostHog/posthog teams")
