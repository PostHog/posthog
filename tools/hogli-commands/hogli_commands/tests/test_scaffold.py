from __future__ import annotations

from pathlib import Path

from hogli_commands.product.isolation import MODEL_SURFACE_PREFIXES, has_narrowed_turbo_inputs, unwatched_model_surface
from hogli_commands.product.paths import load_structure
from hogli_commands.product.scaffold import _render_template, flatten_structure


def _write_scaffold(product_dir: Path) -> None:
    # Renders every template like bootstrap_product does, minus the repo-file edits
    # (tach.toml, settings, db routing) that must not run inside a test.
    structure = load_structure()
    for path, config in flatten_structure(structure.get("root_files", {})).items():
        file_path = product_dir / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(_render_template(config.get("template", ""), "my_product", separate_db=True))
    for path, config in flatten_structure(structure.get("backend_files", {})).items():
        file_path = product_dir / "backend" / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(_render_template(config.get("template", ""), "my_product", separate_db=True))


class TestScaffoldPassesIsolationGates:
    # The baseline header promises a bootstrapped product is sealed from its first
    # commit, so the scaffold must satisfy the same gates product:lint blocks on.

    def test_scaffold_watches_the_model_surface(self, tmp_path: Path) -> None:
        product_dir = tmp_path / "my_product"
        _write_scaffold(product_dir)
        assert unwatched_model_surface(product_dir) == set()

    def test_scaffold_inputs_count_as_narrowed(self, tmp_path: Path) -> None:
        product_dir = tmp_path / "my_product"
        _write_scaffold(product_dir)
        assert has_narrowed_turbo_inputs(product_dir, model_surface=MODEL_SURFACE_PREFIXES) is True
