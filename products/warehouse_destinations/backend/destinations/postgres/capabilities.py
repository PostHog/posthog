"""What the Postgres destination supports. No vendor imports, so reading this loads no SDK."""

from products.warehouse_destinations.backend.facade.contracts import DestinationCapabilities
from products.warehouse_destinations.backend.facade.enums import WriteMode

# APPEND writes straight into the final table, which has no batch-key column, so it cannot
# remove the rows of an earlier attempt.
POSTGRES_CAPABILITIES = DestinationCapabilities(
    write_modes=frozenset({WriteMode.APPEND, WriteMode.MERGE, WriteMode.REPLACE}),
    batch_key_modes=frozenset({WriteMode.MERGE, WriteMode.REPLACE}),
    namespace_depth=1,
    atomic_replace=True,
)
