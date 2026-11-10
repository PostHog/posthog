"""
Facade for experiments product.

This module provides the public interface for other products to interact with experiments.
"""

import importlib
from typing import TYPE_CHECKING, Any

from .contracts import CreateExperimentInput, Experiment, FeatureFlag

if TYPE_CHECKING:
    from .api import count_running_experiments_on_feature_flag_called, create_experiment

# Loaded on first use (PEP 562): light submodules such as `launch_signals` load in every process at
# startup, and importing one runs this file first, so an eager `api` import would drag the whole
# experiments service onto the startup path.
_LAZY_API_NAMES = frozenset({"count_running_experiments_on_feature_flag_called", "create_experiment"})


def __getattr__(name: str) -> Any:
    if name not in _LAZY_API_NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(".api", __name__), name)
    globals()[name] = value
    return value


__all__ = [
    "count_running_experiments_on_feature_flag_called",
    "create_experiment",
    "CreateExperimentInput",
    "Experiment",
    "FeatureFlag",
]
