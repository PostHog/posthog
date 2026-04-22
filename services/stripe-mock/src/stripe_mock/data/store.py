from typing import Any

from stripe_mock.config import settings


class DataStore:
    """In-memory store for mock Stripe data. Loaded once at startup from a scenario."""

    def __init__(self):
        self._collections: dict[str, list[dict[str, Any]]] = {}

    def load_scenario(self, scenario_name: str | None = None) -> None:
        from stripe_mock.data.scenarios import SCENARIOS

        name = scenario_name or settings.scenario
        builder = SCENARIOS.get(name)
        if not builder:
            raise ValueError(f"Unknown scenario: {name}. Available: {list(SCENARIOS.keys())}")

        self._collections = builder()

    def get_collection(self, name: str) -> list[dict[str, Any]]:
        return self._collections.get(name, [])

    def get_by_id(self, collection: str, obj_id: str) -> dict[str, Any] | None:
        for item in self.get_collection(collection):
            if item.get("id") == obj_id:
                return item
        return None

    def filter_by(self, collection: str, field: str, value: Any) -> list[dict[str, Any]]:
        return [item for item in self.get_collection(collection) if item.get(field) == value]

    def collection_names(self) -> list[str]:
        return list(self._collections.keys())

    def summary(self) -> dict[str, int]:
        return {name: len(items) for name, items in self._collections.items()}


store = DataStore()
