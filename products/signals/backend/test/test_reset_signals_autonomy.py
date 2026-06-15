from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command
from django.test import override_settings

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_SERVICE = "products.data_warehouse.backend.data_load.service"


@override_settings(DEBUG=True)
@mock.patch(f"{_SERVICE}.delete_discover_schemas_schedule")
@mock.patch(f"{_SERVICE}.delete_external_data_schedule")
class TestResetSignalsAutonomyDWHTeardown(BaseTest):
    """The reset command must tear down the DWH pipelines the wizard creates, since nothing
    FK-links them to the signals-owned models it already deletes. Scoped to created_via=MCP.

    The Temporal schedule helpers are mocked — this exercises the Postgres soft-deletes and the
    teardown wiring without a live Temporal. `keep_findings`/`keep_log` skip the unrelated
    cleanup_signals (ClickHouse + workflow termination) and log-cycling side effects.
    """

    def _github_source(self, created_via: str, *, deleted: bool = False):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="Github",
            status="Running",
            prefix=f"gh_{created_via}_",
            created_via=created_via,
            deleted=deleted,
            job_inputs={
                "repository": "acme/app",
                "auth_method": {"selection": "oauth", "github_integration_id": "1"},
            },
        )
        schema = ExternalDataSchema.objects.create(team=self.team, source=source, name="issues")
        return source, schema

    def _run_reset(self) -> None:
        call_command(
            "reset_signals_autonomy",
            team_id=self.team.id,
            yes=True,
            keep_findings=True,
            keep_log=True,
        )

    def test_soft_deletes_mcp_created_dwh_source_and_schema(self, mock_delete_schedule, mock_delete_discover) -> None:
        source, schema = self._github_source(ExternalDataSource.CreatedVia.MCP)

        self._run_reset()

        source.refresh_from_db()
        schema.refresh_from_db()
        assert source.deleted is True
        assert source.deleted_at is not None
        assert schema.deleted is True

        # Both the schema sync schedule and the source-level sync schedule are torn down.
        deleted_schedule_ids = {call.args[0] for call in mock_delete_schedule.call_args_list}
        assert str(schema.id) in deleted_schedule_ids
        assert str(source.id) in deleted_schedule_ids
        mock_delete_discover.assert_called_once_with(str(source.id))

    def test_leaves_non_mcp_dwh_source_untouched(self, mock_delete_schedule, mock_delete_discover) -> None:
        # A user's own UI-connected warehouse source of the same type must survive the reset.
        source, schema = self._github_source(ExternalDataSource.CreatedVia.WEB)

        self._run_reset()

        source.refresh_from_db()
        schema.refresh_from_db()
        assert source.deleted is False
        assert schema.deleted is False
        mock_delete_schedule.assert_not_called()
        mock_delete_discover.assert_not_called()

    def test_leaves_non_issue_tracker_source_type_untouched(self, mock_delete_schedule, mock_delete_discover) -> None:
        # Stripe is MCP-created but is not one of the issue-tracker signal sources — scoping is
        # by source_type (derived from _DATA_IMPORT_SOURCE_MAP), not "everything MCP made".
        stripe = ExternalDataSource.objects.create(
            team=self.team,
            source_type="Stripe",
            status="Running",
            prefix="stripe_",
            created_via=ExternalDataSource.CreatedVia.MCP,
        )

        self._run_reset()

        stripe.refresh_from_db()
        assert stripe.deleted is False
        mock_delete_schedule.assert_not_called()
