"""
Facade for experiments product.

This module provides the public interface for other products to interact with experiments.
"""

from .api import create_experiment
from .contracts import CreateExperimentInput, Experiment, FeatureFlag
from .saved_metric_api import (
    create_saved_metric,
    delete_saved_metric,
    get_saved_metric,
    list_saved_metrics,
    update_saved_metric,
)
from .saved_metric_contracts import (
    CreateSavedMetricInput,
    ExperimentSavedMetric,
    ListSavedMetricsInput,
    UpdateSavedMetricInput,
)

__all__ = [
    # Experiments
    "create_experiment",
    "CreateExperimentInput",
    "Experiment",
    "FeatureFlag",
    # Saved Metrics
    "create_saved_metric",
    "update_saved_metric",
    "delete_saved_metric",
    "list_saved_metrics",
    "get_saved_metric",
    "CreateSavedMetricInput",
    "UpdateSavedMetricInput",
    "ExperimentSavedMetric",
    "ListSavedMetricsInput",
]
