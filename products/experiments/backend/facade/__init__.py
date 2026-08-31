"""
Facade for experiments product.

This module provides the public interface for other products to interact with experiments.
"""

from .api import (
    create_experiment,
    create_pulse_experiment_draft,
    create_pulse_experiment_draft_experiment,
    get_pulse_experiment_lifecycle,
    resolve_or_create_pulse_experiment_draft_flag,
)
from .contracts import (
    CreateExperimentInput,
    Experiment,
    FeatureFlag,
    PulseExperimentDraftInput,
    PulseExperimentLifecycleDTO,
    PulseExperimentMetricRef,
    PulseExperimentVariant,
)

__all__ = [
    "create_experiment",
    "get_pulse_experiment_lifecycle",
    "create_pulse_experiment_draft",
    "create_pulse_experiment_draft_experiment",
    "resolve_or_create_pulse_experiment_draft_flag",
    "CreateExperimentInput",
    "Experiment",
    "FeatureFlag",
    "PulseExperimentDraftInput",
    "PulseExperimentLifecycleDTO",
    "PulseExperimentMetricRef",
    "PulseExperimentVariant",
]
