import pytest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.ad_hoc_sync import AdHocSyncTrigger, WorkflowStartError
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

pytestmark = [pytest.mark.django_db]

COMMAND = "products.warehouse_sources.backend.management.commands.resync_schemas_non_billable"
# The pause/stage/start sequence now lives in one place, so that is where it gets stubbed.
SHARED = "products.warehouse_sources.backend.ad_hoc_sync"


@pytest.fixture
def team():
    return create_team(organization=create_organization("test org"))


def _create_schema(team, name="test_table"):
    source = ExternalDataSource.objects.create(team=team, source_type="Postgres", job_inputs={})
    return ExternalDataSchema.objects.create(
        name=name,
        team=team,
        source=source,
        should_sync=True,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={},
    )


@patch(f"{COMMAND}.sync_connect")
@patch(f"{SHARED}.is_schedule_paused", return_value=True)
@patch(f"{SHARED}.start_external_data_workflow")
class TestResyncSchemasNonBillable:
    def test_dry_run_triggers_nothing(self, mock_start, _mock_paused, _mock_connect, team):
        schema = _create_schema(team)

        call_command("resync_schemas_non_billable", schema_ids=str(schema.id))

        mock_start.assert_not_called()

    def test_live_run_triggers_each_schema_as_non_billable(self, mock_start, _mock_paused, _mock_connect, team):
        schemas = [_create_schema(team, name=f"table_{i}") for i in range(2)]

        call_command(
            "resync_schemas_non_billable",
            schema_ids=",".join(str(s.id) for s in schemas),
            live_run=True,
            sleep_seconds=0,
        )

        assert mock_start.call_count == 2
        triggered = set()
        for call in mock_start.call_args_list:
            inputs = call.args[2]
            # A billable bulk resync would charge customers for our own data-correctness fix.
            assert inputs.billable is False
            triggered.add(str(inputs.external_data_schema_id))
        assert triggered == {str(s.id) for s in schemas}

    @pytest.mark.parametrize("reset,expected", [(True, True), (False, False)])
    def test_reset_pipeline_is_staged_only_when_asked(
        self, mock_start, _mock_paused, _mock_connect, team, reset, expected
    ):
        schema = _create_schema(team)

        call_command(
            "resync_schemas_non_billable",
            schema_ids=str(schema.id),
            live_run=True,
            sleep_seconds=0,
            reset=reset,
        )

        schema.refresh_from_db()
        # Staging the reset wipes the table before the re-read, so it must not happen by default.
        assert schema.sync_type_config.get("reset_pipeline", False) is expected

    def test_limit_caps_the_batch(self, mock_start, _mock_paused, _mock_connect, team):
        schemas = [_create_schema(team, name=f"table_{i}") for i in range(3)]

        call_command(
            "resync_schemas_non_billable",
            schema_ids=",".join(str(s.id) for s in schemas),
            live_run=True,
            sleep_seconds=0,
            limit=1,
        )

        assert mock_start.call_count == 1

    @patch(f"{COMMAND}.trigger_ad_hoc_sync")
    def test_one_failure_does_not_strand_the_rest_of_the_batch(
        self, mock_trigger, _mock_start, _mock_paused, _mock_connect, team, capsys
    ):
        schemas = [_create_schema(team, name=f"table_{i}") for i in range(3)]
        mock_trigger.side_effect = [
            WorkflowStartError("temporal down"),
            AdHocSyncTrigger(workflow_id="wf-2", schedule_paused_now=False),
            AdHocSyncTrigger(workflow_id="wf-3", schedule_paused_now=False),
        ]

        call_command(
            "resync_schemas_non_billable",
            schema_ids=",".join(str(s.id) for s in schemas),
            live_run=True,
            sleep_seconds=0,
        )

        # Batching dozens of schemas is the point, so one bad schema must not abort the run.
        assert mock_trigger.call_count == 3
        assert "Triggered: 2, Failed: 1" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "kwargs",
        [{"sleep_seconds": -1}, {"limit": 0}, {"limit": -2}],
        ids=["negative_sleep", "zero_limit", "negative_limit"],
    )
    def test_bad_options_are_rejected_before_anything_is_triggered(
        self, mock_start, _mock_paused, _mock_connect, team, kwargs
    ):
        schemas = [_create_schema(team, name=f"table_{i}") for i in range(3)]

        with pytest.raises(CommandError):
            call_command(
                "resync_schemas_non_billable",
                schema_ids=",".join(str(s.id) for s in schemas),
                live_run=True,
                **kwargs,
            )

        # A negative limit silently drops the last schemas, and a negative sleep raises partway
        # through, so both must fail before a single workflow starts.
        mock_start.assert_not_called()
