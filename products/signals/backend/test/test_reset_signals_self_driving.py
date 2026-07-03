from io import StringIO

from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command
from django.test import override_settings

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

_SERVICE = "products.data_warehouse.backend.logic.data_load.service"


@override_settings(DEBUG=True)
@mock.patch(f"{_SERVICE}.delete_discover_schemas_schedule")
@mock.patch(f"{_SERVICE}.delete_external_data_schedule")
class TestResetSignalsSelfDrivingDWHTeardown(BaseTest):
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
            "reset_signals_self_driving",
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


@override_settings(DEBUG=True)
class TestResetSignalsSelfDrivingProductToggles(BaseTest):
    """The wizard's step-4 product toggles are reset only with --reset-products; before doing so the
    command reports their state, flagging any a run should have enabled but didn't. The plain reset
    leaves product settings untouched."""

    def _run_reset(self, *, reset_products: bool = False) -> str:
        out = StringIO()
        call_command(
            "reset_signals_self_driving",
            team_id=self.team.id,
            yes=True,
            keep_findings=True,
            keep_log=True,
            reset_products=reset_products,
            stdout=out,
        )
        return out.getvalue()

    def _enable_all_products(self) -> None:
        self.team.session_recording_opt_in = True
        self.team.session_recording_masking_config = {"maskAllInputs": True}
        self.team.autocapture_exceptions_opt_in = True
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"widget_public_token": "tok"}
        self.team.save()

    def test_reset_products_turns_toggles_to_fresh_shape(self) -> None:
        self._enable_all_products()

        self._run_reset(reset_products=True)

        self.team.refresh_from_db()
        assert self.team.session_recording_opt_in is False
        assert self.team.session_recording_masking_config is None
        assert self.team.autocapture_exceptions_opt_in is None
        assert self.team.conversations_enabled is None
        assert self.team.conversations_settings is None

    def test_without_flag_leaves_product_toggles_untouched(self) -> None:
        self._enable_all_products()

        output = self._run_reset()

        self.team.refresh_from_db()
        assert self.team.session_recording_opt_in is True
        assert self.team.autocapture_exceptions_opt_in is True
        assert self.team.conversations_enabled is True
        # No product report either — the plain reset says nothing about products.
        assert "Product enablement" not in output

    def test_reset_products_highlights_products_a_run_should_have_enabled(self) -> None:
        # A fresh team has all three OFF — exactly the "wizard didn't enable it" signal.
        output = self._run_reset(reset_products=True)
        assert "should have enabled, but didn't" in output
        for label in ("Session Replay", "Error Tracking", "Support / Conversations"):
            assert label in output
