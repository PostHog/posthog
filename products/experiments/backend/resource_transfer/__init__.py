from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor

from products.experiments.backend.resource_transfer.experiment import ExperimentVisitor
from products.experiments.backend.resource_transfer.experiment_holdout import ExperimentHoldoutVisitor
from products.experiments.backend.resource_transfer.experiment_saved_metric import ExperimentSavedMetricVisitor
from products.experiments.backend.resource_transfer.experiment_to_saved_metric import ExperimentToSavedMetricVisitor

# Core's transfer registry (posthog/models/resource_transfer/registry.py) reads this tuple.
RESOURCE_TRANSFER_VISITORS: tuple[type[ResourceTransferVisitor], ...] = (
    ExperimentVisitor,
    ExperimentHoldoutVisitor,
    ExperimentSavedMetricVisitor,
    ExperimentToSavedMetricVisitor,
)
