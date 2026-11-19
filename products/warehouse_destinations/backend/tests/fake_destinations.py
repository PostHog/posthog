"""Import targets for registry tests that resolve a built-in by its import path."""

from products.warehouse_destinations.backend.facade.contracts import DestinationCapabilities
from products.warehouse_destinations.backend.facade.enums import DestinationType, WriteMode
from products.warehouse_destinations.backend.facade.testing import FakeDestination

CAPABILITIES = DestinationCapabilities(
    write_modes=frozenset({WriteMode.APPEND}),
    batch_key_modes=frozenset(),
    namespace_depth=2,
    atomic_replace=False,
)

build_fake_destination = FakeDestination(destination_type=DestinationType.SNOWFLAKE, capabilities=CAPABILITIES)

NOT_CALLABLE = "not a factory"
NOT_CAPABILITIES = {"write_modes": ["append"]}
