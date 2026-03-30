"""Experiment saved metric service — single source of truth for saved metric business logic."""

from typing import Any
from uuid import uuid4

from django.db import transaction

import pydantic
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentFunnelsQuery,
    ExperimentMeanMetric,
    ExperimentMetricType,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentTrendsQuery,
)

from posthog.models.team.team import Team

from products.experiments.backend.models.experiment import ExperimentSavedMetric


class ExperimentSavedMetricService:
    """Single source of truth for experiment saved metric business logic."""

    LEGACY_QUERY_KINDS = {"ExperimentTrendsQuery", "ExperimentFunnelsQuery"}

    def __init__(self, team: Team, user: Any):
        self.team = team
        self.user = user

    @classmethod
    def validate_query(cls, query: dict | None) -> None:
        """Validate saved metric queries accepted by the API layer."""
        if not query:
            raise ValidationError("Query is required to create a saved metric")

        kind = query.get("kind")
        if kind in cls.LEGACY_QUERY_KINDS:
            raise ValidationError(
                f"Legacy metric kind '{kind}' is no longer supported for new saved metrics. "
                "Use 'ExperimentMetric' instead."
            )

        if kind != "ExperimentMetric":
            raise ValidationError("Metric query kind must be 'ExperimentMetric'")

        try:
            if kind == "ExperimentMetric":
                if "metric_type" not in query:
                    raise ValidationError("ExperimentMetric requires a metric_type")
                if query["metric_type"] == ExperimentMetricType.MEAN:
                    ExperimentMeanMetric(**query)
                elif query["metric_type"] == ExperimentMetricType.FUNNEL:
                    ExperimentFunnelMetric(**query)
                elif query["metric_type"] == ExperimentMetricType.RATIO:
                    ExperimentRatioMetric(**query)
                elif query["metric_type"] == ExperimentMetricType.RETENTION:
                    ExperimentRetentionMetric(**query)
                else:
                    raise ValidationError(
                        "ExperimentMetric metric_type must be 'mean', 'funnel', 'ratio', or 'retention'"
                    )
            elif kind == "ExperimentTrendsQuery":
                ExperimentTrendsQuery(**query)
            elif kind == "ExperimentFunnelsQuery":
                ExperimentFunnelsQuery(**query)
        except pydantic.ValidationError as e:
            raise ValidationError(str(e.errors())) from e

    @transaction.atomic
    def create_saved_metric(
        self,
        *,
        name: str,
        query: dict,
        description: str | None = None,
    ) -> ExperimentSavedMetric:
        """Create a saved metric with full business-logic validation."""
        normalized_query = self._normalize_query_for_write(query)

        return ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name=name,
            description=description,
            query=normalized_query,
        )

    @transaction.atomic
    def update_saved_metric(self, saved_metric: ExperimentSavedMetric, update_data: dict) -> ExperimentSavedMetric:
        """Update a saved metric with full business-logic validation."""
        self._assert_team_ownership(saved_metric)
        self._validate_update_payload(update_data)

        if "query" in update_data:
            existing_uuid = saved_metric.query.get("uuid") if saved_metric.query else None
            update_data["query"] = self._normalize_query_for_write(update_data["query"], existing_uuid=existing_uuid)

        for attr, value in update_data.items():
            setattr(saved_metric, attr, value)

        if update_data:
            saved_metric.save()

        return saved_metric

    @transaction.atomic
    def delete_saved_metric(self, saved_metric: ExperimentSavedMetric) -> None:
        """Delete a saved metric."""
        self._assert_team_ownership(saved_metric)
        saved_metric.delete()

    def _assert_team_ownership(self, saved_metric: ExperimentSavedMetric) -> None:
        if saved_metric.team_id != self.team.id:
            raise ValidationError("Saved metric does not exist or does not belong to this project")

    @classmethod
    def _normalize_query_for_write(cls, query: dict, *, existing_uuid: str | None = None) -> dict:
        cls.validate_query(query)

        normalized_query = dict(query)
        incoming_uuid = normalized_query.get("uuid")

        if existing_uuid and incoming_uuid and incoming_uuid != existing_uuid:
            raise ValidationError("Saved metric UUID cannot be changed")

        if existing_uuid:
            normalized_query["uuid"] = existing_uuid
        elif not incoming_uuid:
            normalized_query["uuid"] = str(uuid4())

        return normalized_query

    @staticmethod
    def _validate_update_payload(update_data: dict) -> None:
        expected_keys = {
            "name",
            "description",
            "query",
        }
        extra_keys = set(update_data.keys()) - expected_keys

        if extra_keys:
            raise ValidationError(f"Can't update keys: {', '.join(sorted(extra_keys))} on ExperimentSavedMetric")
