import sys

import pytest

from products.warehouse_destinations.backend import tests as tests_package
from products.warehouse_destinations.backend.facade.contracts import UnsupportedDestinationError
from products.warehouse_destinations.backend.facade.enums import DestinationType, ErrorKind
from products.warehouse_destinations.backend.facade.testing import FakeDestination
from products.warehouse_destinations.backend.logic import registry
from products.warehouse_destinations.backend.tests import fake_destinations

FAKE_MODULE = "products.warehouse_destinations.backend.tests.fake_destinations"

pytestmark = pytest.mark.usefixtures("empty_registry")


def _builtin(factory: str = "build_fake_destination", capabilities: str = "CAPABILITIES") -> registry._Builtin:
    return registry._Builtin(factory=f"{FAKE_MODULE}:{factory}", capabilities=f"{FAKE_MODULE}:{capabilities}")


@pytest.mark.parametrize("lookup", [registry.resolve, registry.capabilities_for])
def test_unknown_type_is_a_configuration_error(lookup) -> None:
    with pytest.raises(UnsupportedDestinationError, match="Unsupported destination type") as exc_info:
        lookup(DestinationType.SNOWFLAKE)

    assert exc_info.value.kind == ErrorKind.CONFIGURATION
    assert exc_info.value.detail is not None


def test_builtin_resolves_lazily_by_import_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, FAKE_MODULE)
    monkeypatch.delattr(tests_package, "fake_destinations")
    registry._BUILTINS[DestinationType.SNOWFLAKE] = _builtin()

    assert FAKE_MODULE not in sys.modules
    factory = registry.resolve(DestinationType.SNOWFLAKE)

    assert factory is sys.modules[FAKE_MODULE].build_fake_destination
    assert registry.capabilities_for(DestinationType.SNOWFLAKE) is sys.modules[FAKE_MODULE].CAPABILITIES


@pytest.mark.parametrize(
    "builtin, lookup, error, match",
    [
        (registry._Builtin(factory="no_separator", capabilities=""), registry.resolve, ValueError, "must look like"),
        (_builtin(factory="missing_attribute"), registry.resolve, AttributeError, "missing_attribute"),
        (_builtin(factory="NOT_CALLABLE"), registry.resolve, TypeError, "is not callable"),
        (_builtin(capabilities="NOT_CAPABILITIES"), registry.capabilities_for, TypeError, "not DestinationCapab"),
        (
            registry._Builtin(factory="products.warehouse_destinations.no_such_module:f", capabilities=""),
            registry.resolve,
            ModuleNotFoundError,
            "no_such_module",
        ),
    ],
)
def test_bad_builtin_paths_raise(builtin, lookup, error: type[Exception], match: str) -> None:
    registry._BUILTINS[DestinationType.SNOWFLAKE] = builtin

    with pytest.raises(error, match=match):
        lookup(DestinationType.SNOWFLAKE)


def test_override_wins_over_the_builtin_and_restores_it() -> None:
    registry._BUILTINS[DestinationType.SNOWFLAKE] = _builtin()
    outer = FakeDestination()
    inner = FakeDestination()

    with registry.override(DestinationType.SNOWFLAKE, outer):
        with registry.override(DestinationType.SNOWFLAKE, inner):
            assert registry.resolve(DestinationType.SNOWFLAKE) is inner
        assert registry.resolve(DestinationType.SNOWFLAKE) is outer
        assert registry.capabilities_for(DestinationType.SNOWFLAKE) is outer.capabilities

    assert registry.resolve(DestinationType.SNOWFLAKE) is fake_destinations.build_fake_destination


def test_override_restores_after_an_error() -> None:
    with pytest.raises(RuntimeError):
        with registry.override(DestinationType.BIGQUERY, FakeDestination()):
            raise RuntimeError

    assert registry.registered_types() == ()


def test_registered_types_lists_builtins_and_overrides_once_sorted() -> None:
    registry._BUILTINS[DestinationType.SNOWFLAKE] = _builtin()
    registry._BUILTINS[DestinationType.BIGQUERY] = _builtin()

    with registry.override(DestinationType.SNOWFLAKE, FakeDestination()):
        with registry.override(DestinationType.AZURE_BLOB, FakeDestination()):
            assert registry.registered_types() == (
                DestinationType.AZURE_BLOB,
                DestinationType.BIGQUERY,
                DestinationType.SNOWFLAKE,
            )
