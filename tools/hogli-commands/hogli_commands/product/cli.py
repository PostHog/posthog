"""CLI commands for product scaffolding, linting, and maturity scoring."""

from __future__ import annotations

import click

from .lint import lint_all_products, lint_owners, lint_product
from .maturity import generate_codegen_report, generate_detail, generate_report, score_all_products, score_product
from .scaffold import bootstrap_product


@click.command(name="product:bootstrap", help="Scaffold a new product with canonical structure")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Show what would be created without creating")
@click.option("--force", is_flag=True, help="Overwrite existing files")
@click.option("--non-interactive", is_flag=True, help="Skip prompts, use defaults (for CI)")
@click.option(
    "--separate-db/--no-separate-db",
    default=None,
    help="Whether to give the product its own database. "
    "Overrides the interactive prompt; pair with --non-interactive in CI.",
)
@click.option(
    "--db-name",
    default=None,
    help="Database name when --separate-db is set. Defaults to the product name.",
)
@click.option(
    "--owner",
    default=None,
    help="Owning GitHub team slug (e.g. team-product-analytics). "
    "Overrides the interactive prompt; pair with --non-interactive in CI.",
)
@click.option(
    "--display-name",
    default=None,
    help="Human-friendly product name (e.g. 'Warehouse sources'). "
    "Defaults to the product name with underscores → spaces.",
)
def cmd_bootstrap(
    name: str,
    dry_run: bool,
    force: bool,
    non_interactive: bool,
    separate_db: bool | None,
    db_name: str | None,
    owner: str | None,
    display_name: str | None,
) -> None:
    bootstrap_product(
        name,
        dry_run,
        force,
        non_interactive=non_interactive,
        separate_db_override=separate_db,
        db_name_override=db_name,
        owner_override=owner,
        display_name_override=display_name,
    )


@click.command(name="product:lint", help="Check product structure for misplaced files")
@click.argument("name", required=False)
@click.option("--all", "lint_all", is_flag=True, help="Lint all products")
def cmd_lint(name: str | None, lint_all: bool) -> None:
    if lint_all:
        lint_all_products()
        return

    if not name:
        raise click.UsageError("Provide a product name or use --all")

    click.echo(f"Linting product '{name}'...\n")
    issues = lint_product(name, verbose=True, detailed=True)
    click.echo("")

    if not issues:
        click.echo("✓ All checks passed")
        return

    click.echo("Issues:\n")
    for issue in issues:
        click.echo(f"  • {issue}")
    raise SystemExit(1)


@click.command(
    name="product:lint:owners",
    help="Validate product.yaml owners against PostHog/posthog collaborator teams. "
    "Pass product names to limit to those (CI passes the list derived from changed yamls); "
    "no args = sweep every product.",
)
@click.argument("names", nargs=-1)
def cmd_lint_owners(names: tuple[str, ...]) -> None:
    lint_owners(list(names))


@click.command(name="product:maturity", help="Score product maturity across isolation dimensions")
@click.argument("name", required=False)
@click.option("--all", "score_all", is_flag=True, help="Score all products and generate ranked report")
@click.option("--codegen", "codegen_detail", is_flag=True, help="Show detailed codegen call-site analysis")
def cmd_maturity(name: str | None, score_all: bool, codegen_detail: bool) -> None:
    if codegen_detail:
        products = None if score_all or not name else [name]
        click.echo(generate_codegen_report(products))
        return

    if score_all:
        scores = score_all_products()
        click.echo(generate_report(scores))
        return

    if not name:
        raise click.UsageError("Provide a product name or use --all")

    from .paths import PRODUCTS_DIR

    product_dir = PRODUCTS_DIR / name
    if not product_dir.exists():
        raise click.ClickException(f"Product '{name}' not found at {product_dir}")

    ps = score_product(name)
    click.echo(generate_detail(ps))
