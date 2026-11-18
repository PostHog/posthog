"""The experiment scope: watch the sessions of people exposed to an experiment, label each by variant."""

from typing import Any

from pydantic import BaseModel, Field

from posthog.schema import RecordingsQuery

from products.replay_vision.backend.models.replay_scanner import apply_experiment_targeting


class ExperimentScopeSettings(BaseModel, frozen=True):
    """The stored shape of an experiment scope, under `scope` once `kind` is stripped.

    `variants` names every watched variant. The two older stores could both leave it unset to mean
    "every variant", so a scope derived from one of them carries whatever they held; the API fills
    the full list from the flag when it starts accepting a scope as input.
    """

    experiment_id: int = Field(ge=1)
    variants: list[str] | None = None
    # `variants` came from the experiment's full variant set when the scanner was made
    # ("all_at_creation") or from a person picking a subset ("user"). The launch receiver adds newly
    # created variants to the first and leaves the second alone.
    variants_source: str | None = None


class ExperimentScope:
    kind = "experiment"

    def __init__(self, settings: ExperimentScopeSettings) -> None:
        self.settings = settings

    def recordings_filter(self, query: RecordingsQuery) -> RecordingsQuery:
        """Set the query's exposure filter, through the same helper the two older stores use, so a
        scope and the store it was derived from narrow a query identically."""
        return apply_experiment_targeting(query, self.as_targeting())

    def as_targeting(self) -> dict[str, Any]:
        """This scope in the legacy `experiment_targeting` shape, for the readers that still take one."""
        return {"experiment_id": self.settings.experiment_id, "variants": self.settings.variants}

    def as_stored(self) -> dict[str, Any]:
        return {"kind": self.kind, **self.settings.model_dump(exclude_none=True)}
