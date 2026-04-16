"""
Facade for experiments product.

This module provides the public interface for other products to interact with experiments.
"""

from .api import create_experiment
from .contracts import CreateExperimentInput, CreateFeatureFlagInput, Experiment, FeatureFlag, FeatureFlagVariant

__all__ = [
    "create_experiment",
    "CreateExperimentInput",
    "CreateFeatureFlagInput",
    "Experiment",
    "FeatureFlag",
    "FeatureFlagVariant",
]
