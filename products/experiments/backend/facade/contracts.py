"""
Facade contracts (DTOs) for experiments product.

These are framework-free frozen dataclasses that define the interface
between the experiments product and the rest of the system.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CreateExperimentInput:
    """
    Input for creating an experiment.

    Note: This class is NOT hashable when dict/list fields are non-None due to
    mutable types. Use only immutable fields if hashability is required.
    """

    # Required fields
    name: str
    feature_flag_key: str

    # Optional basic fields
    description: str = ""
    type: str = "product"

    # Feature flag configuration
    parameters: dict[str, Any] | None = None

    # Metrics configuration
    metrics: list[dict] | None = None
    metrics_secondary: list[dict] | None = None
    secondary_metrics: list[dict] | None = None
    metrics_ordering: tuple[str, ...] | None = None  # primary_metrics_ordered_uuids
    secondary_metrics_ordering: tuple[str, ...] | None = None  # secondary_metrics_ordered_uuids
    saved_metrics_ids: list[dict] | None = None

    # Statistics and exposure configuration
    stats_config: dict | None = None
    exposure_criteria: dict | None = None
    only_count_matured_users: bool | None = None

    # Experiment lifecycle
    start_date: datetime | None = None
    end_date: datetime | None = None
    archived: bool = False
    deleted: bool = False
    conclusion: str | None = None
    conclusion_comment: str | None = None

    # Advanced configuration
    holdout_id: int | None = None  # We'll pass ID, facade will load the model
    filters: dict | None = None
    scheduling_config: dict | None = None
    create_in_folder: str | None = None

    # Internal flags
    allow_unknown_events: bool = False
    serializer_context: dict | None = None


@dataclass(frozen=True)
class FeatureFlag:
    """Feature flag output."""

    id: int
    key: str
    active: bool
    created_at: datetime
    name: str | None = None


@dataclass(frozen=True)
class Experiment:
    """Experiment output."""

    id: int
    name: str
    feature_flag_id: int
    feature_flag_key: str
    is_draft: bool
    created_at: datetime
    description: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    updated_at: datetime | None = None
