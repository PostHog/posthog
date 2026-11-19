"""Write the typed config module of every built-in destination from its spec.

Run it with `pnpm generate:destination-configs` after a change to a `destinations/*/spec.py`.
A test fails when the committed modules differ from what this command writes.
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from products.warehouse_destinations.backend.logic import registry
from products.warehouse_destinations.backend.logic.config_generator import (
    config_module_name,
    format_source,
    render_config_module,
)

REPO_ROOT = Path(__file__).parents[5]
CONFIGS_DIR = REPO_ROOT / "products" / "warehouse_destinations" / "backend" / "facade" / "configs"
# Modules in the configs package that people write. The command never writes or removes them.
HAND_WRITTEN_MODULES = frozenset({"__init__.py", "base.py"})


def generate_config_modules() -> dict[Path, str]:
    """The formatted source of every generated config module, keyed by its path."""
    modules: dict[Path, str] = {}
    for destination_type in registry.builtin_types():
        module_path, _, attribute = registry.spec_import_path(destination_type).partition(":")
        spec_file = Path(*module_path.split(".")).with_suffix(".py")
        source = render_config_module(registry.spec_for(destination_type), spec_location=f"{attribute} in {spec_file}")
        path = CONFIGS_DIR / f"{config_module_name(destination_type)}.py"
        modules[path] = format_source(source, path=str(path))
    return modules


def stale_config_modules(modules: dict[Path, str]) -> list[Path]:
    """Generated modules on disk that no built-in destination produces any more."""
    return sorted(
        path for path in CONFIGS_DIR.glob("*.py") if path.name not in HAND_WRITTEN_MODULES and path not in modules
    )


class Command(BaseCommand):
    help = "Generate the typed config classes of the warehouse destinations from their specs"

    def handle(self, *args, **options) -> None:
        modules = generate_config_modules()
        for path, source in modules.items():
            path.write_text(source)
            self.stdout.write(f"Wrote {path.relative_to(REPO_ROOT)}")
        for path in stale_config_modules(modules):
            path.unlink()
            self.stdout.write(f"Removed {path.relative_to(REPO_ROOT)}")
