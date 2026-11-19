import pytest

from products.warehouse_destinations.backend.logic import registry


@pytest.fixture
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_registry", {})
    monkeypatch.setattr(registry, "_BUILTIN_FACTORIES", {})
