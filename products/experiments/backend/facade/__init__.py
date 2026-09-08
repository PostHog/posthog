"""
Facade for experiments product.

This module provides the public interface for other products to interact with experiments.
"""

from .api import create_experiment, create_pulse_experiment_draft
from .contracts import (
    CreateExperimentInput,
    Experiment,
    FeatureFlag,
    PulseExperimentDraftInput,
    PulseExperimentDraftResult,
)

__all__ = [
    "create_experiment",
    "create_pulse_experiment_draft",
    "CreateExperimentInput",
    "Experiment",
    "FeatureFlag",
    "PulseExperimentDraftInput",
    "PulseExperimentDraftResult",
]
