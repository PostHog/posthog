"""Experiment saved metric service — single source of truth for saved metric business logic."""

from typing import Any
from uuid import uuid4

from django.db import transaction

from rest_framework.exceptions import ValidationError

from posthog.models.team.team import Team

from products.experiments.backend.metric_utils import without_action_names
from products.experiments.backend.metric_validation import (
    UNITLESS_CONVERSION_WINDOW_ERROR,
    extract_entity_nodes,
    first_unitless_conversion_window,
    parse_and_validate_metric,
    validate_metric_action_ids,
)
from products.experiments.backend.models.experiment import ExperimentSavedMetric, saved_metric_has_legacy_query
from products.experiments.backend.warehouse_access_control import enforce_warehouse_metric_access


class ExperimentSavedMetricService:
    """Single source of truth for experiment saved metric business logic."""

    def __init__(self, team: Team, user: Any):
        self.team = team
        self.user = user

    @classmethod
    def validate_query(cls, query: dict | None) -> None:
        """Validate saved metric queries accepted by the API layer."""
        if not query:
            raise ValidationError("Query is required to create a saved metric")
        parse_and_validate_metric(query, error_prefix="Invalid metric: ")

    @transaction.atomic
    def create_saved_metric(
        self,
        *,
        name: str,
        query: dict,
        description: str | None = None,
    ) -> ExperimentSavedMetric:
        """Create a saved metric with full business-logic validation."""
        normalized_query = self.normalize_query_for_write(query)
        validate_metric_action_ids([normalized_query], self.team.id)
        enforce_warehouse_metric_access([normalized_query], team=self.team, user=self.user)

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
        self._validate_update_payload(update_data, saved_metric)

        if "query" in update_data:
            update_data["query"] = self.normalize_query_for_write(
                update_data["query"], existing_query=saved_metric.query
            )
            _, stored_action_ids = extract_entity_nodes([saved_metric.query] if saved_metric.query else [])
            validate_metric_action_ids([update_data["query"]], self.team.id, known_action_ids=stored_action_ids)
            enforce_warehouse_metric_access([update_data["query"]], team=self.team, user=self.user)

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
    def normalize_query_for_write(cls, query: dict, *, existing_query: dict | None = None) -> dict:
        existing_uuid = existing_query.get("uuid") if existing_query else None
        # Clients resend the whole query on any edit, including a rename or a tag change. A stored
        # query that comes back unchanged is not validated again, so a rule added after it was saved
        # does not block those edits.
        is_unchanged = (
            bool(query)
            and existing_query is not None
            and without_action_names(query) == without_action_names(existing_query)
        )
        if not is_unchanged:
            cls.validate_query(query)

        normalized_query = dict(query)
        incoming_uuid = normalized_query.get("uuid")

        if existing_uuid and incoming_uuid and incoming_uuid != existing_uuid:
            raise ValidationError("Saved metric UUID cannot be changed")

        if existing_uuid:
            normalized_query["uuid"] = existing_uuid
        else:
            # A caller promoting an inline metric sends its uuid; keeping it would make the
            # shared metric and the inline one read each other's results.
            normalized_query["uuid"] = str(uuid4())

        # The skip above covers only a query that comes back unchanged. An edit to another field
        # resends the stored unit-less window in a changed query, so this rule matches the stored
        # window itself. The normalized query carries the stored row's identity, so compare under
        # that identity.
        stored_for_match = [{**existing_query, "uuid": normalized_query["uuid"]}] if existing_query else []
        if first_unitless_conversion_window([normalized_query], stored_for_match) is not None:
            raise ValidationError(f"Invalid metric: {UNITLESS_CONVERSION_WINDOW_ERROR}")

        return normalized_query

    @staticmethod
    def _validate_update_payload(update_data: dict, saved_metric: ExperimentSavedMetric) -> None:
        # Block all updates to legacy saved metrics
        if saved_metric_has_legacy_query(saved_metric):
            raise ValidationError(
                "This saved metric uses a legacy query format and cannot be updated. "
                "Please create a new saved metric with the ExperimentMetric format instead."
            )

        expected_keys = {
            "name",
            "description",
            "query",
        }
        extra_keys = set(update_data.keys()) - expected_keys

        if extra_keys:
            raise ValidationError(f"Can't update keys: {', '.join(sorted(extra_keys))} on ExperimentSavedMetric")
