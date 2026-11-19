import sys

import pytest

from products.warehouse_destinations.backend import tests as tests_package
from products.warehouse_destinations.backend.facade.contracts import UnsupportedDestinationError
from products.warehouse_destinations.backend.logic import registry
from products.warehouse_destinations.backend.tests import fake_destinations

FAKE_MODULE = "products.warehouse_destinations.backend.tests.fake_destinations"

pytestmark = pytest.mark.usefixtures("empty_registry")


def _other_factory(connection, *, logger=None):
    return fake_destinations.FakeDestination(connection, logger=logger)


def test_resolve_returns_registered_factory() -> None:
    registry.register("Fake", fake_destinations.build_fake_destination)

    assert registry.resolve("Fake") is fake_destinations.build_fake_destination


def test_register_rejects_duplicate() -> None:
    registry.register("Fake", fake_destinations.build_fake_destination)

    with pytest.raises(ValueError, match="already registered for destination type 'Fake'"):
        registry.register("Fake", _other_factory)

    assert registry.resolve("Fake") is fake_destinations.build_fake_destination


def test_register_with_replace_overrides() -> None:
    registry.register("Fake", fake_destinations.build_fake_destination)
    registry.register("Fake", _other_factory, replace=True)

    assert registry.resolve("Fake") is _other_factory


def test_register_rejects_type_that_has_a_builtin() -> None:
    registry._BUILTIN_FACTORIES["Fake"] = f"{FAKE_MODULE}:build_fake_destination"

    with pytest.raises(ValueError, match="already registered"):
        registry.register("Fake", _other_factory)

    registry.register("Fake", _other_factory, replace=True)
    assert registry.resolve("Fake") is _other_factory


@pytest.mark.parametrize("destination_type", ["Unknown", "", "fake"])
def test_resolve_unknown_type_raises(destination_type: str) -> None:
    registry.register("Fake", fake_destinations.build_fake_destination)

    with pytest.raises(UnsupportedDestinationError, match="Unsupported destination type"):
        registry.resolve(destination_type)


def test_resolve_imports_builtin_on_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, FAKE_MODULE)
    monkeypatch.delattr(tests_package, "fake_destinations")
    registry._BUILTIN_FACTORIES["Fake"] = f"{FAKE_MODULE}:build_fake_destination"

    assert FAKE_MODULE not in sys.modules
    factory = registry.resolve("Fake")

    assert FAKE_MODULE in sys.modules
    assert factory is sys.modules[FAKE_MODULE].build_fake_destination


@pytest.mark.parametrize(
    "import_path, error, match",
    [
        ("no_separator", ValueError, "must look like"),
        (f"{FAKE_MODULE}:", ValueError, "must look like"),
        (":build_fake_destination", ValueError, "must look like"),
        (f"{FAKE_MODULE}:missing_attribute", AttributeError, "missing_attribute"),
        (f"{FAKE_MODULE}:NOT_CALLABLE", TypeError, "is not callable"),
        ("products.warehouse_destinations.no_such_module:factory", ModuleNotFoundError, "no_such_module"),
    ],
)
def test_resolve_rejects_bad_builtin_path(import_path: str, error: type[Exception], match: str) -> None:
    registry._BUILTIN_FACTORIES["Fake"] = import_path

    with pytest.raises(error, match=match):
        registry.resolve("Fake")


def test_registered_types_lists_registered_and_builtin_types_once() -> None:
    registry._BUILTIN_FACTORIES["Postgres"] = f"{FAKE_MODULE}:build_fake_destination"
    registry._BUILTIN_FACTORIES["BigQuery"] = f"{FAKE_MODULE}:build_fake_destination"
    registry.register("Fake", fake_destinations.build_fake_destination)
    registry.register("Postgres", fake_destinations.build_fake_destination, replace=True)

    assert registry.registered_types() == ("BigQuery", "Fake", "Postgres")
