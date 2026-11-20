"""Product bootstrapping — scaffold new products and register them in config files."""

from __future__ import annotations

import re
import sys
import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import click

from .paths import DB_ROUTING_YAML, DJANGO_SETTINGS, FRONTEND_PACKAGE_JSON, PRODUCTS_DIR, REPO_ROOT, load_structure


def flatten_structure(files: dict, prefix: str = "", result: dict | None = None) -> dict[str, dict]:
    """
    Flatten nested structure dict into flat paths.
    e.g., {"facade/": {"api.py": {...}}} -> {"facade/api.py": {...}}
    """
    if result is None:
        result = {}
    for name, config in files.items():
        if name.endswith("/"):
            flatten_structure(config, prefix + name, result)
        else:
            result[prefix + name] = config if isinstance(config, dict) else {}
    return result


def _team_scope_template_vars(*, separate_db: bool) -> dict[str, str]:
    """Pick the right team-scoped base class for the chosen DB layout.

    Separate-DB products can't FK to Team across databases, so they use
    `ProductTeamModel` (team_id as BigIntegerField). Main-DB products use
    `TeamScopedRootMixin` and declare a regular FK on the subclass. Both
    bundle `TeamScopedManager` so models start fail-closed.
    """
    if separate_db:
        return {
            "team_base_mixin": "ProductTeamModel",
            "team_base_import": "from posthog.models.scoping.product_mixin import ProductTeamModel",
        }
    return {
        "team_base_mixin": "TeamScopedRootMixin",
        "team_base_import": "from posthog.models.scoping.root_mixin import TeamScopedRootMixin",
    }


def _render_template(template: str, product_name: str, *, separate_db: bool) -> str:
    pascal_name = "".join(word.capitalize() for word in product_name.split("_"))
    return template.format(
        product=product_name,
        product_kebab=product_name.replace("_", "-"),
        Product=pascal_name,
        **_team_scope_template_vars(separate_db=separate_db),
    )


def _register_in_file(
    file_path: Path, label: str, needle: str, write_fn: Callable[[str], str | None], *, dry_run: bool
) -> None:
    """Register a product entry in a config file. Skips if needle already present."""
    if not file_path.exists():
        return
    content = file_path.read_text()
    if needle in content:
        click.echo(f"\n  Already in {label}: {needle}")
        return
    if dry_run:
        click.echo(f"\n  Would add to {label}: {needle}")
        return
    result = write_fn(content)
    if result is not None:
        file_path.write_text(result)
        click.echo(f"\n  Added to {label}: {needle}")


def _add_to_frontend_package_json(product_name: str, *, dry_run: bool) -> None:
    pkg_name = f"@posthog/products-{product_name.replace('_', '-')}"

    def write(content: str) -> str:
        data = json.loads(content)
        deps = data.get("dependencies", {})
        deps[pkg_name] = "workspace:*"
        data["dependencies"] = dict(sorted(deps.items()))
        return json.dumps(data, indent=4) + "\n"

    _register_in_file(FRONTEND_PACKAGE_JSON, "frontend/package.json", pkg_name, write, dry_run=dry_run)


def _append_to_products_apps(content: str, app_config: str) -> str | None:
    match = re.search(r"^PRODUCTS_APPS = \[\n.*?^\]$", content, re.MULTILINE | re.DOTALL)
    if match is None:
        return None
    insert_pos = match.end() - 1
    return content[:insert_pos] + f'    "{app_config}",\n' + content[insert_pos:]


def _add_to_django_settings(product_name: str, *, dry_run: bool) -> None:
    pascal_name = "".join(word.capitalize() for word in product_name.split("_"))
    app_config = f"products.{product_name}.backend.apps.{pascal_name}Config"

    def write(content: str) -> str | None:
        updated = _append_to_products_apps(content, app_config)
        if updated is None:
            click.echo(f"\n  Could not find the PRODUCTS_APPS list — add manually: {app_config}")
        return updated

    _register_in_file(DJANGO_SETTINGS, "Django settings", app_config, write, dry_run=dry_run)


def _get_existing_databases() -> list[str]:
    """Read unique database names from db_routing.yaml."""
    if not DB_ROUTING_YAML.exists():
        return []
    import yaml

    config = yaml.safe_load(DB_ROUTING_YAML.read_text()) or {}
    return sorted({r["database"] for r in config.get("routes", []) if r.get("database")})


def _add_to_db_routing(product_name: str, database_name: str, *, dry_run: bool) -> None:
    route_entry = f"    - app_label: {product_name}\n      database: {database_name}\n"

    def write(content: str) -> str:
        return content.rstrip() + "\n" + route_entry

    _register_in_file(
        DB_ROUTING_YAML,
        "products/db_routing.yaml",
        f"app_label: {product_name}",
        write,
        dry_run=dry_run,
    )


_VALID_PRODUCT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _default_display_name(product_name: str) -> str:
    return product_name.replace("_", " ").capitalize()


def _write_product_yaml(product_dir: Path, display_name: str, owners: list[str], *, dry_run: bool) -> None:
    yaml_path = product_dir / "product.yaml"
    owners_yaml = "\n".join(f"  - {o}" for o in owners)
    content = f"name: {display_name}\nowners:\n{owners_yaml}\n"
    if dry_run:
        click.echo(f"\n  Would create product.yaml:\n{content}")
        return
    yaml_path.write_text(content)
    click.echo(f"\n  Created product.yaml (name={display_name!r}, owners={owners})")


def _prompt_for_separate_db(name: str) -> tuple[bool, str | None]:
    """Ask the operator whether the new product gets its own database.

    Returns (separate_db, db_name). `db_name` is None when the operator
    opts to share the main DB. Asked up front (before file generation)
    so the model template can branch on the answer — separate-DB needs
    `ProductTeamModel`, main-DB needs `TeamScopedRootMixin`.
    """
    click.echo(
        "\n  Products get their own database by default — this isolates locks, "
        "connections, and migrations so one product can't bring down the app. "
        "This is new but fully working. Reach out in #team-devex with questions."
    )
    click.secho(
        "  ⚠ Adding a route here is only the Django side. The database must also "
        "be provisioned by #team-infrastructure (Terraform + charts).",
        fg="yellow",
    )
    existing_dbs = _get_existing_databases()
    if existing_dbs:
        click.echo(f"  Existing databases: {', '.join(existing_dbs)}")
        click.echo("  You can share a database with another product from the same team.")

    if click.confirm("  Skip separate database?", default=False):
        click.echo("  Using the main database. Models will inherit TeamScopedRootMixin.")
        return False, None

    db_name = click.prompt("  Database name", default=name, show_default=True)
    click.echo(f"  Using separate database '{db_name}'. Models will inherit ProductTeamModel.")
    return True, db_name


def _hoglint_command() -> str | None:
    """The hoglint of the venv that runs hogli, else the one on PATH."""
    venv_hoglint = Path(sys.executable).parent / "hoglint"
    if venv_hoglint.exists():
        return str(venv_hoglint)
    return shutil.which("hoglint")


def _record_isolated_level(name: str) -> None:
    # The scaffold's turbo.json narrows the contract-check inputs, so the product claims hoglint's
    # Isolated level. The ledger records each group that passes a level, and `hoglint compare`
    # fails a pull request whose ledger lacks the new product's line.
    ledger_step = (
        "Commit hoglint.ledger in a commit of its own, after the product, "
        "so that a reviewer sees the ledger change apart from the code."
    )
    hoglint = _hoglint_command()
    if hoglint is None:
        click.secho(
            f"\n  ⚠ hoglint is not installed, so hoglint.ledger lacks the line for {name}. "
            f"Run `hoglint check --write-ledger`. {ledger_step}",
            fg="yellow",
        )
        return
    click.echo(f"\n  Recording the Isolated level of {name} in hoglint.ledger (hoglint check --write-ledger)…")
    result = subprocess.run([hoglint, "check", "--write-ledger"], cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        click.secho(
            f"  ⚠ hoglint check --write-ledger exited {result.returncode}, so hoglint.ledger may lack the line "
            f"for {name}. Run it again and fix what it reports. {ledger_step}",
            fg="yellow",
        )
        return
    click.secho(f"  Added the level line for {name} to hoglint.ledger. {ledger_step}", fg="cyan")


def bootstrap_product(
    name: str,
    dry_run: bool,
    force: bool,
    *,
    non_interactive: bool = False,
    separate_db_override: bool | None = None,
    db_name_override: str | None = None,
    owner_override: str | None = None,
    display_name_override: str | None = None,
) -> None:
    if not _VALID_PRODUCT_NAME_RE.match(name):
        raise click.ClickException(
            f"Invalid product name '{name}' — must be lowercase, start with a letter, and contain only [a-z0-9_]."
        )
    product_dir = PRODUCTS_DIR / name

    if product_dir.exists() and not force:
        raise click.ClickException(f"Product '{name}' already exists at {product_dir}. Use --force to overwrite.")

    # Resolve the DB layout up front so file rendering can branch on it.
    # Precedence: explicit --separate-db/--no-separate-db override > non-interactive
    # default > interactive prompt. The non-interactive default stays separate-DB
    # to match the previous CI behavior.
    if separate_db_override is not None:
        separate_db = separate_db_override
        db_name = (db_name_override or name) if separate_db else None
    elif dry_run or non_interactive:
        separate_db, db_name = True, db_name_override or name
    else:
        separate_db, db_name = _prompt_for_separate_db(name)

    structure = load_structure()
    created: list[str] = []
    skipped: list[str] = []

    for path, config in flatten_structure(structure.get("root_files", {})).items():
        if not config.get("scaffold", True):
            continue
        file_path = product_dir / path
        if dry_run:
            (skipped if (file_path.exists() and not force) else created).append(path)
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists() and not force:
            skipped.append(path)
            continue
        file_path.write_text(_render_template(config.get("template", ""), name, separate_db=separate_db))
        created.append(path)

    for path, config in flatten_structure(structure.get("backend_files", {})).items():
        if not config.get("scaffold", True):
            continue
        file_path = product_dir / "backend" / path
        label = f"backend/{path}"
        if dry_run:
            (skipped if (file_path.exists() and not force) else created).append(label)
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists() and not force:
            skipped.append(label)
            continue
        file_path.write_text(_render_template(config.get("template", ""), name, separate_db=separate_db))
        created.append(label)

    for folder_name in structure.get("frontend_files", {}).keys():
        folder_path = product_dir / "frontend" / folder_name.rstrip("/")
        label = f"frontend/{folder_name}"
        if dry_run:
            created.append(label)
        else:
            folder_path.mkdir(parents=True, exist_ok=True)
            created.append(label)

    click.echo(f"{'Would create' if dry_run else 'Created'} product '{name}' at {product_dir}")
    if created:
        click.echo(f"\n  Created {len(created)} files/folders:")
        for path in created:
            click.echo(f"    {path}")
    if skipped:
        click.echo(f"\n  Skipped {len(skipped)} existing files:")
        for path in skipped:
            click.echo(f"    {path}")

    # product.yaml — canonical metadata.
    # Precedence: explicit --display-name / --owner override > non-interactive
    # default > interactive prompt.
    display_name = display_name_override or _default_display_name(name)
    if dry_run:
        owners = [owner_override] if owner_override else ["team-CHANGEME"]
        _write_product_yaml(product_dir, display_name, owners, dry_run=True)
    elif non_interactive or owner_override is not None or display_name_override is not None:
        owners = [owner_override] if owner_override else ["team-devex"]
        _write_product_yaml(product_dir, display_name, owners, dry_run=False)
        if not owner_override:
            click.secho("  ⚠ No --owner provided. Set the real team slug in product.yaml before merging.", fg="yellow")
    else:
        prompted_display_name = click.prompt("  Display name", default=display_name, show_default=True)
        owner = click.prompt(
            "  Owning GitHub team slug (e.g. team-product-analytics)",
            default="",
            show_default=False,
        )
        owners = [owner] if owner else ["team-CHANGEME"]
        _write_product_yaml(product_dir, prompted_display_name, owners, dry_run=False)
        if not owner:
            click.secho("  ⚠ Set the real team slug in product.yaml before merging.", fg="yellow")

    _add_to_frontend_package_json(name, dry_run=dry_run)
    _add_to_django_settings(name, dry_run=dry_run)

    if separate_db and db_name is not None:
        _add_to_db_routing(name, db_name, dry_run=dry_run)
    elif not dry_run:
        click.echo("  Skipped db_routing entry. Models live in the main database.")

    if not dry_run:
        _record_isolated_level(name)
        mixin = "ProductTeamModel" if separate_db else "TeamScopedRootMixin"
        click.secho(
            f"\n  Models inherit `{mixin}` (fail-closed team scoping). "
            "Read posthog/models/scoping/README.md for the contract before writing your first model.",
            fg="cyan",
        )
