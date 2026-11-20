from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import DestinationRunContext
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DestinationConfigurationError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.azure_blob import (
    AzureBlobDestinationWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.key_prefix import (
    run_object_prefix,
)

STARTED = dt.datetime(2026, 3, 5, 7, 8, 9, tzinfo=dt.UTC)


def _ctx(prefix: str | None, run_started_at: dt.datetime | None = STARTED, **config: str) -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id="schema",
        source_id="source",
        job_id="job",
        run_uuid="run-a1",
        destination_id="destination",
        destination_type="AzureBlob",
        destination_name="test destination",
        table_name="charges",
        sync_type="full_refresh",
        config={"prefix": prefix, **config},
        run_started_at=run_started_at,
    )


@pytest.mark.parametrize(
    ("prefix", "run_started_at", "expected"),
    [
        (None, STARTED, "charges/run-a1/"),
        ("posthog/", STARTED, "posthog/charges/run-a1/"),
        ("{year}/{month}/{day}/{table}/", STARTED, "2026/03/05/charges/run-a1/"),
        ("exports/{year}-{month}-{day}T{hour}{minute}{second}", STARTED, "exports/2026-03-05T070809/charges/run-a1/"),
        (
            "{year}/{month}/{day}",
            dt.datetime(2026, 3, 5, 1, 0, tzinfo=dt.timezone(dt.timedelta(hours=2))),
            "2026/03/04/charges/run-a1/",
        ),
        ("{year}/{table}/", None, "{year}/{table}/charges/run-a1/"),
    ],
    ids=["no_prefix", "plain", "date_and_table", "time", "utc", "no_start_time"],
)
def test_run_object_prefix(prefix: str | None, run_started_at: dt.datetime | None, expected: str) -> None:
    assert run_object_prefix(_ctx(prefix, run_started_at)) == expected


@pytest.mark.parametrize(
    "prefix", ["{year}/{foo}/", "{year:>9}", "{0}/"], ids=["unknown_variable", "format_spec", "positional"]
)
def test_a_prefix_the_renderer_rejects_is_a_configuration_error(prefix: str) -> None:
    with pytest.raises(DestinationConfigurationError, match="key prefix"):
        run_object_prefix(_ctx(prefix))


class LocalAzureBlobWriter(AzureBlobDestinationWriter):
    def __init__(self, ctx: DestinationRunContext, container: mock.MagicMock) -> None:
        super().__init__(ctx)
        self._fake = container

    @asynccontextmanager
    async def _container_client(self) -> AsyncIterator[mock.MagicMock]:
        yield self._fake


@pytest.mark.asyncio
async def test_the_azure_manifest_goes_under_the_rendered_prefix() -> None:
    ctx = _ctx("{year}/{month}/{day}/{table}/", container_name="example-container")
    container = mock.MagicMock()
    container.get_blob_client.return_value = mock.AsyncMock()

    await LocalAzureBlobWriter(ctx, container).finalize_run(ctx)

    container.get_blob_client.assert_called_once_with("2026/03/05/charges/run-a1/_manifest.json")
