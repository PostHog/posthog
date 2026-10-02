"""
Facade for experiments product.

This module provides the public interface for other products to interact with experiments.
"""

from .api import count_running_experiments_on_feature_flag_called, create_experiment
from .contracts import CreateExperimentInput, Experiment, FeatureFlag

__all__ = [
    "count_running_experiments_on_feature_flag_called",
    "create_experiment",
    "CreateExperimentInput",
    "Experiment",
    "FeatureFlag",
]
