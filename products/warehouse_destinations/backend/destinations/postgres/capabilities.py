"""What the Postgres destination supports. No vendor imports, so reading this loads no SDK."""

from products.warehouse_destinations.backend.facade.contracts import DestinationCapabilities
from products.warehouse_destinations.backend.facade.enums import WriteMode

POSTGRES_CAPABILITIES = DestinationCapabilities(
    write_modes=frozenset({WriteMode.APPEND, WriteMode.MERGE, WriteMode.REPLACE}),
    batch_key_modes=frozenset({WriteMode.APPEND, WriteMode.MERGE, WriteMode.REPLACE}),
    namespace_depth=1,
    atomic_replace=True,
)
