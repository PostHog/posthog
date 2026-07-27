from typing import Any

from .common.registry import SourceRegistry

__all__ = ["SourceRegistry", "load_all_sources"]


def load_all_sources() -> None:
    """Import every source module so each registers itself with ``SourceRegistry``.

    Deferred out of module scope so importing a leaf (e.g. ``sources.stripe.constants``)
    doesn't drag every vendor SDK at app startup. Importing ``_load_all`` runs each
    source module's ``@SourceRegistry.register`` decorator. Idempotent — re-imports are
    cheap dict lookups in ``sys.modules``.
    """
    from . import _load_all  # noqa: F401, PLC0415


def __getattr__(name: str) -> Any:
    # Back-compat: source classes used to be re-exported here. Resolve them lazily so
    # `from ...sources import StripeSource` keeps working without eager-loading every SDK.
    # Guard private/dunder names (including `_load_all` itself) to avoid recursing through
    # the very import we use to populate the namespace.
    if name.startswith("_"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import _load_all  # noqa: PLC0415

    try:
        return getattr(_load_all, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
