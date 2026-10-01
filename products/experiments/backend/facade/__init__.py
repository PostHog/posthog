"""
Facade for experiments product.

This module provides the public interface for other products to interact with experiments.
"""

from .api import count_running_experiments_started_before_exposure_cutoff, create_experiment
from .contracts import CreateExperimentInput, Experiment, FeatureFlag

__all__ = [
    "count_running_experiments_started_before_exposure_cutoff",
    "create_experiment",
    "CreateExperimentInput",
    "Experiment",
    "FeatureFlag",
]
