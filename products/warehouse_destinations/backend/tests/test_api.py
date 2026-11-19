import pytest

import structlog

from products.warehouse_destinations.backend.facade import api
from products.warehouse_destinations.backend.facade.contracts import DestinationConnection, UnsupportedDestinationError
from products.warehouse_destinations.backend.tests.fake_destinations import FakeDestination, build_fake_destination

pytestmark = pytest.mark.usefixtures("empty_registry")


@pytest.mark.parametrize("with_logger", [True, False])
def test_get_destination_passes_connection_and_logger(with_logger: bool) -> None:
    api.register_destination("Fake", build_fake_destination)
    connection = DestinationConnection(destination_type="Fake", team_id=7, config={"host": "db.example.com"})
    logger = structlog.get_logger("test") if with_logger else None

    destination = api.get_destination(connection, logger=logger)

    assert isinstance(destination, FakeDestination)
    assert destination.connection is connection
    assert destination.logger is logger


def test_get_destination_dispatches_on_destination_type() -> None:
    api.register_destination("Fake", build_fake_destination)

    with pytest.raises(UnsupportedDestinationError):
        api.get_destination(DestinationConnection(destination_type="Snowflake", team_id=1))


def test_register_destination_rejects_duplicate_unless_replace() -> None:
    api.register_destination("Fake", build_fake_destination)

    with pytest.raises(ValueError):
        api.register_destination("Fake", build_fake_destination)

    api.register_destination("Fake", build_fake_destination, replace=True)
    assert api.supported_destination_types() == ("Fake",)
