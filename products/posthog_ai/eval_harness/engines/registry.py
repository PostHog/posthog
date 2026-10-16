"""Engine registry: resolve an ``EvalEngine`` by name.

Suite modules can select an engine with ``EVAL_ENGINE``. Suites without that
marker use the default engine.
"""

from __future__ import annotations

from .base import EvalEngine
from .braintrust import BraintrustEngine
from .posthog import PostHogEngine

_ENGINES: dict[str, type[EvalEngine]] = {
    BraintrustEngine.name: BraintrustEngine,
    PostHogEngine.name: PostHogEngine,
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
