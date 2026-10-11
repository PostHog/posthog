# Hand-written resolver for the generated per-source config modules in this package.
# `pnpm generate:source-configs` (re)writes the per-source modules; it never touches this file.
import importlib

from products.warehouse_sources.backend.temporal.data_imports.sources import (
    TOP_LEVEL_SOURCES_PACKAGE,
    source_module_path,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import Config
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config_module_name(source: ExternalDataSourceType) -> str:
    source_module = source_module_path(source)
    if source_module is not None and source_module.startswith(f"{TOP_LEVEL_SOURCES_PACKAGE}."):
        return f"{source_module.removesuffix('.source')}._config"
    name = source.name if isinstance(source, ExternalDataSourceType) else source  # DEMO (warehouse source plugins)
    return f"{__package__}.{name.lower()}"


def get_config_for_source(source: ExternalDataSourceType) -> type[Config]:
    """Resolve a source's generated config class.

    Module and class names are derived from the enum member (`<name.lower()>.py`,
    `<value>SourceConfig`) — the same rule the generator uses to emit them — so adding a
    source needs no change here. A vendor in the top-level `sources` package keeps its
    config in `sources/<vendor>/_config.py` instead. Static importers should import the
    class from its per-source module directly (e.g. `from ...generated_configs.stripe import
    StripeSourceConfig`).
    """
    module = importlib.import_module(_config_module_name(source))
    # DEMO (warehouse source plugins): `str()` is the member's value, and the plugin string itself.
    return getattr(module, f"{source}SourceConfig")
