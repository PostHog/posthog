"""
Facade for experiments product.

This module provides the public interface for other products to interact with experiments.
"""

from .api import create_experiment, create_pulse_experiment_draft, get_pulse_experiment_lifecycle
from .contracts import (
    CreateExperimentInput,
    Experiment,
    FeatureFlag,
    PulseExperimentDraftInput,
    PulseExperimentDraftResult,
    PulseExperimentLifecycleResult,
)

__all__ = [
    "create_experiment",
    "create_pulse_experiment_draft",
    "get_pulse_experiment_lifecycle",
    "CreateExperimentInput",
    "Experiment",
    "FeatureFlag",
    "PulseExperimentDraftInput",
    "PulseExperimentDraftResult",
    "PulseExperimentLifecycleResult",
]
