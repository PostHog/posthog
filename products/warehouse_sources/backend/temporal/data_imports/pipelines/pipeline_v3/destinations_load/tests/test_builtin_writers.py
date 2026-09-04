import pytest

from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.presentation.views.external_data_destination import (
    DESTINATION_INTEGRATION_KINDS,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationRunContext,
    DestinationWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.registry import (
    resolve_destination_writer,
    supported_destination_types,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.builtin_writers import (
    builtin_destination_types,
    register_builtin_destination_writers,
)

# Azure Blob and S3 validate their config eagerly at construction time (a missing container or
# bucket would otherwise write to a nonsense name hundreds of MiB into a batch), so those two
# need enough config to pass that check. Every other builtin writer accepts an empty config here.
_MINIMAL_CONFIG: dict[str, dict] = {
    str(ExternalDataDestination.Type.AZURE_BLOB): {"container_name": "container"},
    str(ExternalDataDestination.Type.S3): {"bucket": "bucket", "region": "us-east-1"},
}


def _ctx(destination_type: str) -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id="schema",
        source_id="source",
        job_id="job",
        run_uuid="run-a1",
        destination_id="destination",
        destination_type=destination_type,
        destination_name=destination_type,
        table_name="charges",
        sync_type="incremental",
        primary_keys=("id",),
        config=_MINIMAL_CONFIG.get(destination_type, {}),
    )


@pytest.fixture(autouse=True)
def _registered():
    register_builtin_destination_writers()


@pytest.mark.parametrize("destination_type", sorted(DESTINATION_INTEGRATION_KINDS))
def test_every_type_a_user_can_configure_has_a_writer(destination_type: str) -> None:
    # Without this, a user could create a destination the consumer leases work for and then
    # fails every batch of, because nothing knows how to write it.
    writer = resolve_destination_writer(_ctx(destination_type))

    assert isinstance(writer, DestinationWriter)


def test_the_default_claim_scope_matches_what_can_be_written() -> None:
    # Claiming a type with no writer would lease the group and fail its every batch.
    assert sorted(builtin_destination_types()) == sorted(supported_destination_types())


def test_only_the_warehouse_holds_the_sync_lock_and_runs_post_load() -> None:
    # Both are warehouse-only capabilities. An external writer claiming either would either
    # block the schema's next sync or try to register a warehouse table that does not exist.
    for destination_type in DESTINATION_INTEGRATION_KINDS:
        writer = resolve_destination_writer(_ctx(destination_type))
        assert writer.holds_sync_lock is False, destination_type
        assert writer.runs_post_load is False, destination_type


def test_the_warehouse_is_not_written_by_the_external_consumer() -> None:
    # The warehouse is delivered by the Delta loader, so the external consumer must not claim it.
    assert ExternalDataDestination.Type.POSTHOG_WAREHOUSE not in builtin_destination_types()
