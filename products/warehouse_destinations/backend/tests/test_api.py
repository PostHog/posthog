import os
import sys
import json
import subprocess

import pytest

import structlog

from products.warehouse_destinations.backend.facade import api
from products.warehouse_destinations.backend.facade.contracts import DestinationConnection, UnsupportedDestinationError
from products.warehouse_destinations.backend.facade.enums import DestinationType, WriteMode
from products.warehouse_destinations.backend.facade.testing import FakeDestination, override_destination


@pytest.mark.parametrize("with_logger", [True, False])
def test_get_destination_passes_the_connection_to_the_factory(with_logger: bool) -> None:
    fake = FakeDestination(destination_type=DestinationType.SNOWFLAKE)
    connection = DestinationConnection(destination_type=DestinationType.SNOWFLAKE, team_id=7, config={"a": 1})
    logger = structlog.get_logger("test") if with_logger else None

    with override_destination(DestinationType.SNOWFLAKE, fake):
        destination = api.get_destination(connection, logger=logger)

    assert destination is fake
    assert fake.connections == [connection]


def test_unsupported_types_raise_from_every_lookup() -> None:
    connection = DestinationConnection(destination_type=DestinationType.SNOWFLAKE, team_id=1)

    with pytest.raises(UnsupportedDestinationError):
        api.get_destination(connection)
    with pytest.raises(UnsupportedDestinationError):
        api.get_capabilities(DestinationType.SNOWFLAKE)
    assert DestinationType.SNOWFLAKE not in api.supported_destination_types()


def test_override_destination_changes_capabilities_and_supported_types_only_inside() -> None:
    fake = FakeDestination(destination_type=DestinationType.BIGQUERY)

    with override_destination(DestinationType.BIGQUERY, fake):
        assert api.get_capabilities(DestinationType.BIGQUERY) is fake.capabilities
        assert DestinationType.BIGQUERY in api.supported_destination_types()

    assert DestinationType.BIGQUERY not in api.supported_destination_types()


# Run in a fresh interpreter, because this test session has already imported the vendor SDKs.
_IMPORT_PROBE = """
import json, sys
import products.warehouse_destinations.backend.facade.api as api
import products.warehouse_destinations.backend.facade.testing
import products.warehouse_destinations.backend.core.json_type
import products.warehouse_destinations.backend.core.table
import products.warehouse_destinations.backend.core.table_marker
import products.warehouse_destinations.backend.core.transformer
import products.warehouse_destinations.backend.core.validation
from products.warehouse_destinations.backend.facade.enums import DestinationType
capabilities = api.get_capabilities(DestinationType.POSTGRES)
print(json.dumps({
    "vendor_modules": sorted(m for m in sys.modules if m.split(".")[0] in ("psycopg", "psycopg_binary")),
    "write_modes": sorted(capabilities.write_modes),
    "batch_key_modes": sorted(capabilities.batch_key_modes),
    "namespace_depth": capabilities.namespace_depth,
}))
"""


def test_facade_core_and_postgres_capabilities_load_no_vendor_sdk() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        env={**os.environ, "DEBUG": "1"},
        check=True,
    )

    probe = json.loads(result.stdout.strip().splitlines()[-1])
    assert probe == {
        "vendor_modules": [],
        "write_modes": sorted(WriteMode),
        "batch_key_modes": [WriteMode.MERGE, WriteMode.REPLACE],
        "namespace_depth": 1,
    }
