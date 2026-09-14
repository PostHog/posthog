import uuid
from typing import Any

import pytest
from unittest.mock import patch

from django.core.management import call_command

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

pytestmark = [pytest.mark.django_db]

COMMAND = "backfill_mongodb_server_versions"
PROBE = "products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.get_mongo_connection_metadata"


@pytest.fixture
def team():
    return create_team(organization=create_organization("test org"))


def _create_source(team, host: str) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        source_type="MongoDB",
        job_inputs={"connection_string": f"mongodb://user:pass@{host}/db", "database_name": "db"},
    )


def test_preview_run_probes_but_writes_nothing(team) -> None:
    source = _create_source(team, "reachable.example.com")

    with patch(PROBE, return_value={"engine": "mongodb", "server_version": "4.0.28", "wire_version": 7}) as probe:
        call_command(COMMAND)

    # Asserting the probe ran is what separates "the command declined to write" from "the command
    # never selected the source", which would make the assertion below pass for the wrong reason.
    assert probe.call_count == 1
    source.refresh_from_db()
    assert source.connection_metadata == {}


def test_unreachable_source_does_not_stop_the_survey(team) -> None:
    unreachable = _create_source(team, "unreachable.example.com")
    reachable = _create_source(team, "reachable.example.com")

    def probe(connection_string: str, team_id: int) -> dict[str, Any]:
        if "unreachable" in connection_string:
            raise TimeoutError("server selection timed out")
        return {"engine": "mongodb", "server_version": "7.0.14", "wire_version": 21}

    with patch(PROBE, side_effect=probe):
        call_command(COMMAND, "--live-run")

    unreachable.refresh_from_db()
    reachable.refresh_from_db()
    assert unreachable.connection_metadata == {}
    assert reachable.connection_metadata["server_version"] == "7.0.14"
    assert reachable.connection_metadata["wire_version"] == 21
