from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor

if TYPE_CHECKING:
    from posthog.models.team import Team


class ExperimentToSavedMetricVisitor(
    ResourceTransferVisitor,
    kind="ExperimentToSavedMetric",
    excluded_fields=["created_at", "updated_at"],
    user_facing=False,
    friendly_name="Experiment to saved metric link",
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.experiments.backend.models.experiment import ExperimentToSavedMetric

        return ExperimentToSavedMetric

    @classmethod
    def get_resource_team(cls, resource: Any) -> Team:
        return resource.experiment.team
