"""Engine registry: resolve an ``EvalEngine`` by name.

There is no ``--engine`` CLI flag yet — the default is the only entry until a
second engine exists — but ``EvalContext.engine`` and preflight both resolve
through here, so adding one is a one-line change.
"""

from __future__ import annotations

from .base import EvalEngine
from .braintrust import BraintrustEngine

_ENGINES: dict[str, type[EvalEngine]] = {
    BraintrustEngine.name: BraintrustEngine,
}

DEFAULT_ENGINE = BraintrustEngine.name


def resolve_engine(name: str = DEFAULT_ENGINE) -> EvalEngine:
    """Return a fresh engine instance for ``name`` (the Braintrust engine by default)."""
    try:
        engine_cls = _ENGINES[name]
    except KeyError:
        known = ", ".join(sorted(_ENGINES))
        raise ValueError(f"Unknown eval engine '{name}'; known engines: {known}") from None
    return engine_cls()
