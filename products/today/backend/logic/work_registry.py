from collections.abc import Mapping
from functools import cache

from posthog.dataclasses import frozen
from posthog.products import load_product_modules

from ..facade.contracts import WorkSource

SOURCES_MODULE = "facade.today_work"
SOURCES_ATTRIBUTE = "WORK_SOURCES"


class WorkRegistryError(Exception):
    pass


@frozen
class WorkRegistry:
    sources: Mapping[str, WorkSource]
    products: Mapping[str, str]


def _product(module_name: str) -> str:
    # Product apps are named `products.<product>.backend`.
    return module_name.split(".")[1]


@cache
def load_registry() -> WorkRegistry:
    """Every work source that a product declares in `backend/facade/today_work.py`, by name.

    Today imports no product by name, so the dependency points from the product to Today's facade.
    A broken declaration raises instead of dropping the source without a trace.
    """
    sources: dict[str, WorkSource] = {}
    owners: dict[str, str] = {}
    for module in load_product_modules(SOURCES_MODULE):
        declared = getattr(module, SOURCES_ATTRIBUTE, None)
        if not isinstance(declared, tuple | list):
            raise WorkRegistryError(f"{module.__name__}.{SOURCES_ATTRIBUTE} must be a tuple of WorkSource")
        for source in declared:
            if (
                not isinstance(source, WorkSource)
                or not source.name
                or not callable(source.find)
                or not isinstance(source.scopes, tuple)
                or not all(isinstance(scope, str) and ":" in scope for scope in source.scopes)
            ):
                raise WorkRegistryError(f"{module.__name__} declares {source!r}, which is not a usable WorkSource")
            if source.name in sources:
                raise WorkRegistryError(
                    f"{module.__name__} and {owners[source.name]} both declare the work source name {source.name!r}"
                )
            sources[source.name] = source
            owners[source.name] = module.__name__
    return WorkRegistry(
        sources={name: sources[name] for name in sorted(sources)},
        products={name: _product(module_name) for name, module_name in owners.items()},
    )
