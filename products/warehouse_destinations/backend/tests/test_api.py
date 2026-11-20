import os
import sys
import json
import subprocess
from pathlib import Path

import pytest

import structlog

from products.warehouse_destinations.backend.facade import api
from products.warehouse_destinations.backend.facade.contracts import DestinationConnection, UnsupportedDestinationError
from products.warehouse_destinations.backend.facade.enums import DestinationType, WriteMode
from products.warehouse_destinations.backend.facade.testing import FakeDestination, fake_config, override_destination


@pytest.mark.parametrize("with_logger", [True, False])
def test_get_destination_passes_the_connection_to_the_factory(with_logger: bool) -> None:
    fake = FakeDestination(destination_type=DestinationType.SNOWFLAKE)
    connection = DestinationConnection(team_id=7, config=fake_config(DestinationType.SNOWFLAKE))
    logger = structlog.get_logger("test") if with_logger else None

    with override_destination(DestinationType.SNOWFLAKE, fake):
        destination = api.get_destination(connection, logger=logger)

    assert destination is fake
    assert fake.connections == [connection]


def test_unsupported_types_raise_from_every_lookup() -> None:
    connection = DestinationConnection(team_id=1, config=fake_config(DestinationType.SNOWFLAKE))

    with pytest.raises(UnsupportedDestinationError):
        api.get_destination(connection)
    with pytest.raises(UnsupportedDestinationError):
        api.get_capabilities(DestinationType.SNOWFLAKE)
    with pytest.raises(UnsupportedDestinationError):
        api.get_destination_spec(DestinationType.SNOWFLAKE)
    with pytest.raises(UnsupportedDestinationError):
        api.parse_destination_config(DestinationType.SNOWFLAKE, {})
    assert DestinationType.SNOWFLAKE not in api.supported_destination_types()


def test_override_destination_changes_capabilities_and_supported_types_only_inside() -> None:
    fake = FakeDestination(destination_type=DestinationType.BIGQUERY)

    with override_destination(DestinationType.BIGQUERY, fake):
        assert api.get_capabilities(DestinationType.BIGQUERY) is fake.capabilities
        assert DestinationType.BIGQUERY in api.supported_destination_types()

    assert DestinationType.BIGQUERY not in api.supported_destination_types()


# Run in a fresh interpreter, because this test session has already imported the vendor SDKs.
REPO_ROOT = Path(__file__).resolve().parents[4]

_IMPORT_PROBE = """
import json, sys
import products.warehouse_destinations.backend.facade.api as api
import products.warehouse_destinations.backend.facade.testing
import products.warehouse_destinations.backend.facade.configs.postgres
import products.warehouse_destinations.backend.destinations.postgres.spec
import products.warehouse_destinations.backend.core.json_type
import products.warehouse_destinations.backend.core.table
import products.warehouse_destinations.backend.core.table_marker
import products.warehouse_destinations.backend.core.transformer
import products.warehouse_destinations.backend.core.validation
from products.warehouse_destinations.backend.facade.enums import DestinationType
capabilities = api.get_capabilities(DestinationType.POSTGRES)
spec = api.get_destination_spec(DestinationType.POSTGRES)
config = api.parse_destination_config(DestinationType.POSTGRES, {"database": "db", "auth_method": {"integration_id": 1}})
print(json.dumps({
    "vendor_modules": sorted(m for m in sys.modules if m.split(".")[0] in ("psycopg", "psycopg_binary")),
    "write_modes": sorted(capabilities.write_modes),
    "batch_key_modes": sorted(capabilities.batch_key_modes),
    "namespace_depth": capabilities.namespace_depth,
    "spec_type": spec.destinationType,
    "config_class": type(config).__name__,
}))
"""


def test_facade_core_and_postgres_capabilities_spec_and_config_load_no_vendor_sdk() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        env={**os.environ, "DEBUG": "1"},
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr

    probe = json.loads(result.stdout.strip().splitlines()[-1])
    assert probe == {
        "vendor_modules": [],
        "write_modes": sorted(WriteMode),
        "batch_key_modes": sorted(WriteMode),
        "namespace_depth": 1,
        "spec_type": "Postgres",
        "config_class": "PostgresDestinationConfig",
    }
