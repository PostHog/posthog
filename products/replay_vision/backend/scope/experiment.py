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
    # Mirrors the native type's `balance_variants`, which the scope replaces. True spends the
    # budget about evenly across the watched variants; False samples them proportionally to
    # rollout. The default matches `ExperimentScanner.balance_variants`, so a scope that omits it
    # samples the way the scanner it was derived from did.
    balance: bool = True
    # Lifecycle intent rather than scan config: the scanner is saved disabled against a draft
    # experiment, and the launch receiver turns it on. Mirrors the native type's `start_on_launch`.
    start_on_launch: bool = False


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
        """The blob to persist, carrying only the keys that say something.

        `exclude_defaults` keeps a field whose value is its default out of the blob, so adding a
        defaulted field does not change what an existing row stores. The mirror decides whether it
        owns a row's scope by comparing the stored blob against a fresh derivation, so a shape that
        moved under it would make it read every mirrored row as one set directly by hand.

        `exclude_none` still applies to `variants` and `variants_source`, whose default is None.
        """
        return {"kind": self.kind, **self.settings.model_dump(exclude_defaults=True, exclude_none=True)}
