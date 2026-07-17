"""
Facade for revenue_analytics.

Re-exports the person-join helpers cross-product consumers use to wire revenue joins onto
warehouse sources. Lazy (PEP 562) — the joins module pulls HogQL.
"""

_B = "products.revenue_analytics.backend."

_LAZY = {
    "ensure_person_join": "joins",
    "remove_person_join": "joins",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
