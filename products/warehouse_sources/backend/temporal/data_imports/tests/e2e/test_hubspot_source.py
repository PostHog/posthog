"""Tests for the Hubspot source.

NOTE: Some of these tests require access to the Hubspot API. These are marked with `SKIP_IF_MISSING_HUBSPOT_CREDENTIALS`.
To run these tests you'll need:
- A Hubspot account
- The HUBSPOT_APP_CLIENT_ID and HUBSPOT_APP_CLIENT_SECRET environment variables (these are required for OAuth2
    authentication)
- The HUBSPOT_SECRET_KEY and HUBSPOT_REFRESH_TOKEN environment variables.
    - You can obtain these by running the PostHog app locally, then linking a new Hubspot source using OAuth2 then
        grabbing these from the database (in external_data_source.job_inputs)

Then you can run the tests using:

```
OBJECT_STORAGE_ENDPOINT=http://localhost:19000 \
    HUBSPOT_SECRET_KEY="..." \
    HUBSPOT_REFRESH_TOKEN="..." \
    HUBSPOT_APP_CLIENT_SECRET="..." \
    HUBSPOT_APP_CLIENT_ID="..." \
pytest products/warehouse_sources/backend/temporal/data_imports/tests/e2e/test_hubspot_source.py
```
"""

import os
import uuid

import pytest

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.tests.e2e.conftest import run_external_data_job_workflow

pytestmark = pytest.mark.usefixtures("minio_client")

REQUIRED_ENV_VARS = (
    "HUBSPOT_SECRET_KEY",
    "HUBSPOT_REFRESH_TOKEN",
    # These are needed for HubSpot OAuth app
    "HUBSPOT_APP_CLIENT_ID",
    "HUBSPOT_APP_CLIENT_SECRET",
)


def hubspot_env_vars_are_set() -> bool:
    if not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS):
        return False
    return True


SKIP_IF_MISSING_HUBSPOT_CREDENTIALS = pytest.mark.skipif(
    not hubspot_env_vars_are_set(),
    reason="Hubspot required env vars are not set",
)


@pytest.fixture
def external_data_source(team):
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Hubspot",
        job_inputs={
            "hubspot_secret_key": os.environ["HUBSPOT_SECRET_KEY"],
            "hubspot_refresh_token": os.environ["HUBSPOT_REFRESH_TOKEN"],
        },
    )
    return source


@pytest.fixture
def external_data_schema_full_refresh(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name="contacts",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )
    return schema


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@SKIP_IF_MISSING_HUBSPOT_CREDENTIALS
async def test_hubspot_source_full_refresh(team, external_data_source, external_data_schema_full_refresh):
    """Test that a full refresh sync works as expected.

    Since this is using the Hubspot API, we don't know how many rows we'll get.
    """
    table_name = "hubspot.contacts"

    res = await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_full_refresh,
        table_name=table_name,
        expected_rows_synced=None,
        expected_total_rows=None,
    )
    # just assert some basic properties of the results
    assert res.results is not None
    assert len(res.results) > 0
    assert res.columns is not None
    assert len(res.columns) > 0
    assert "id" in res.columns
