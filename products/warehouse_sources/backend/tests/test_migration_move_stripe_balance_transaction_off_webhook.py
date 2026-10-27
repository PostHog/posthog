from typing import Any

from posthog.test.base import TestMigrations

from django.db import connection


class TestMoveStripeBalanceTransactionOffWebhook(TestMigrations):
    migrate_from = "0187_repin_teamtailor_api_version"
    migrate_to = "0188_move_stripe_balance_transaction_off_webhook"

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        # The base class migrates back to the latest state after Django has closed the
        # connection, which leaves it open. Close it so later non-DB tests in the same shard
        # that call close_old_connections() don't hit pytest-django's database blocker.
        connection.close()

    def setUpBeforeMigration(self, apps: Any) -> None:
        ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
        ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

        def schema(source_type: str, name: str, sync_type: str, sync_type_config: dict | None = None) -> str:
            source = ExternalDataSource.objects.create(
                team_id=self.team.id,
                source_id="source-id",
                connection_id="connection-id",
                status="Completed",
                source_type=source_type,
            )
            created = ExternalDataSchema.objects.create(
                team_id=self.team.id,
                source=source,
                name=name,
                should_sync=True,
                sync_type=sync_type,
                sync_type_config=sync_type_config or {},
            )
            return str(created.id)

        self.moved = schema("Stripe", "BalanceTransaction", "webhook", {"initial_sync_complete": True})
        self.unchanged = {
            schema("Stripe", "BalanceTransaction", "full_refresh"): "full_refresh",
            schema("Stripe", "Invoice", "webhook"): "webhook",
            schema("Postgres", "BalanceTransaction", "webhook"): "webhook",
        }

    def test_moves_only_stripe_balance_transaction_webhook_schemas_to_append_with_reset(self) -> None:
        assert self.apps is not None
        ExternalDataSchema = self.apps.get_model("warehouse_sources", "ExternalDataSchema")

        moved = ExternalDataSchema.objects.get(id=self.moved)
        assert moved.sync_type == "append"
        assert moved.sync_type_config == {
            "initial_sync_complete": True,
            "incremental_field": "created",
            "incremental_field_type": "integer",
            "reset_pipeline": True,
        }

        sync_types = dict(ExternalDataSchema.objects.filter(id__in=self.unchanged).values_list("id", "sync_type"))
        assert {str(schema_id): sync_type for schema_id, sync_type in sync_types.items()} == self.unchanged
