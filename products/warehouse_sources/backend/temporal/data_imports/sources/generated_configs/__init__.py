# Hand-written resolver for the generated per-source config modules in this package.
# `pnpm generate:source-configs` (re)writes the per-source modules; it never touches this file.
import importlib

from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import Config
from products.warehouse_sources.backend.types import ExternalDataSourceType


def get_config_for_source(source: ExternalDataSourceType) -> type[Config]:
    """Resolve a source's generated config class.

    Module and class names are derived from the enum member (`<name.lower()>.py`,
    `<value>SourceConfig`) — the same rule the generator uses to emit them — so adding a
    source needs no change here. Static importers should import the class from its
    per-source module directly (e.g. `from ...generated_configs.stripe import
    StripeSourceConfig`).
    """
    module = importlib.import_module(f".{source.name.lower()}", __package__)
    return getattr(module, f"{source.value}SourceConfig")
