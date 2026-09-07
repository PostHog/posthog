"""The decision "can this run request be served from the materialized table".

Shared by the execution service (which decides the execution path) and the run
throttle (which grants the materialized rate budget), so the two cannot disagree.
"""

from datetime import datetime
from typing import Any

from posthog.schema import EndpointRefreshMode, EndpointRunRequest

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.api import is_materialization_fresh
from products.endpoints.backend.logic.strategies import EndpointQueryStrategy
from products.endpoints.backend.models import EndpointVersion


@frozen
class MaterializedServingState:
    """What a version's materialized table can answer, captured at one moment.

    Small enough to live in the throttle cache: classifying a request then needs
    only this snapshot and the request body, with no database read.
    """

    ready: bool
    materialized_at: datetime | None
    freshness_seconds: int | None
    servable_variables: frozenset[str]

    def serves(self, data: EndpointRunRequest) -> bool:
        if not self.ready or self.materialized_at is None:
            return False
        if not is_materialization_fresh(self.materialized_at, self.freshness_seconds):
            return False
        if data.refresh == EndpointRefreshMode.DIRECT:
            return False
        if data.variables:
            requested = set(data.variables.keys())
            if not self.servable_variables or not requested.issubset(self.servable_variables):
                return False
        return True

    def to_cache(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "materialized_at": self.materialized_at.isoformat() if self.materialized_at else None,
            "freshness_seconds": self.freshness_seconds,
            "servable_variables": sorted(self.servable_variables),
        }

    @classmethod
    def from_cache(cls, payload: dict[str, Any]) -> "MaterializedServingState":
        materialized_at = payload.get("materialized_at")
        return cls(
            ready=bool(payload.get("ready")),
            materialized_at=datetime.fromisoformat(materialized_at) if materialized_at else None,
            freshness_seconds=payload.get("freshness_seconds"),
            servable_variables=frozenset(payload.get("servable_variables") or ()),
        )

    @classmethod
    def not_ready(cls) -> "MaterializedServingState":
        return cls(ready=False, materialized_at=None, freshness_seconds=None, servable_variables=frozenset())


def serving_state_for_version(
    version: EndpointVersion,
    strategy: EndpointQueryStrategy,
    *,
    ready: bool,
    materialized_at: datetime | None,
) -> MaterializedServingState:
    return MaterializedServingState(
        ready=ready,
        materialized_at=materialized_at,
        freshness_seconds=version.data_freshness_seconds,
        servable_variables=frozenset(strategy.materialized_variable_names()) if ready else frozenset(),
    )
