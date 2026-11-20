from __future__ import annotations

import ast
from pathlib import Path

from hogli_commands.product.checks import CheckContext, SystemChecksCheck
from hogli_commands.product.paths import DJANGO_SETTINGS, load_structure
from hogli_commands.product.scaffold import _append_to_products_apps, _render_template, flatten_structure


def _write_scaffold(product_dir: Path) -> None:
    # Renders every template like bootstrap_product does, minus the repo-file edits
    # (tach.toml, settings, db routing) that must not run inside a test.
    structure = load_structure()
    for path, config in flatten_structure(structure.get("root_files", {})).items():
        if not config.get("scaffold", True):
            continue
        file_path = product_dir / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(_render_template(config.get("template", ""), "my_product", separate_db=True))
    for path, config in flatten_structure(structure.get("backend_files", {})).items():
        if not config.get("scaffold", True):
            continue
        file_path = product_dir / "backend" / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(_render_template(config.get("template", ""), "my_product", separate_db=True))


class TestScaffoldPassesTheLint:
    # A bootstrapped product passes product:lint from its first commit. hoglint judges its
    # isolation; CI checks the scaffold with `hoglint check`.

    def test_scaffold_passes_the_system_checks_lint(self, tmp_path: Path) -> None:
        product_dir = tmp_path / "my_product"
        _write_scaffold(product_dir)
        ctx = CheckContext(
            name="my_product",
            product_dir=product_dir,
            backend_dir=product_dir / "backend",
            has_facade_contracts=True,
            structure=load_structure(),
        )
        assert SystemChecksCheck().run(ctx).issues == []


def _list_assignment(source: str, name: str) -> list[str]:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return [ast.literal_eval(element) for element in node.value.elts]  # type: ignore[attr-defined]
    raise AssertionError(f"{name} not found")


def test_new_app_config_lands_in_products_apps() -> None:
    settings = DJANGO_SETTINGS.read_text()
    app_config = "products.my_product.backend.apps.MyProductConfig"

    updated = _append_to_products_apps(settings, app_config)

    assert updated is not None
    assert _list_assignment(updated, "PRODUCTS_APPS") == [*_list_assignment(settings, "PRODUCTS_APPS"), app_config]
    assert updated.count(app_config) == 1
