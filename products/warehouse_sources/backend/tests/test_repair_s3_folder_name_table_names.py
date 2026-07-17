import uuid
import importlib

from posthog.test.base import BaseTest

from django.db import connection

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

# The migration module name starts with a digit, so import it dynamically to run its real SQL.
_migration = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0022_repair_s3_folder_name_table_names"
)
REPAIR_SQL = _migration.REPAIR_SQL


class TestRepairS3FolderNameTableNames(BaseTest):
    def _source(self, source_type: str, prefix: str = "") -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type=source_type,
            prefix=prefix,
        )

    def _schema_with_table(
        self, source: ExternalDataSource, name: str, s3_folder_name: str | None, table_name: str
    ) -> tuple[ExternalDataSchema, DataWarehouseTable]:
        table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name=table_name,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://bucket/x/*",
            external_data_source=source,
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source=source, name=name, s3_folder_name=s3_folder_name, table=table
        )
        return schema, table

    def _run(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(REPAIR_SQL)

    def test_renames_affected_camelcase_table(self) -> None:
        # Stripe CamelCase: table got the snake_cased folder name; should revert to the lower-cased raw name.
        _, table = self._schema_with_table(
            self._source("Stripe"),
            name="CustomerBalanceTransaction",
            s3_folder_name="customer_balance_transaction",
            table_name="stripe_customer_balance_transaction",
        )
        self._run()
        table.refresh_from_db()
        assert table.name == "stripe_customerbalancetransaction"

    def test_leaves_directquery_table_untouched(self) -> None:
        # DuckLake / direct-query tables are stored as the raw schema name (not via build_table_name),
        # so they must NOT match and must NOT be renamed.
        _, table = self._schema_with_table(
            self._source("Postgres", prefix="DuckConfig"),
            name="ducklake_column",
            s3_folder_name="ducklake_column",
            table_name="ducklake_column",
        )
        self._run()
        table.refresh_from_db()
        assert table.name == "ducklake_column"

    def test_leaves_multi_schema_pin_untouched(self) -> None:
        # Legacy multi-schema pin: dotted name, table pinned to the original folder — correct, skip.
        _, table = self._schema_with_table(
            self._source("Postgres"),
            name="public.users",
            s3_folder_name="users",
            table_name="postgres_users",
        )
        self._run()
        table.refresh_from_db()
        assert table.name == "postgres_users"

    def test_leaves_already_correct_table_untouched(self) -> None:
        _, table = self._schema_with_table(
            self._source("Stripe"),
            name="Charge",
            s3_folder_name="charge",
            table_name="stripe_charge",
        )
        self._run()
        table.refresh_from_db()
        assert table.name == "stripe_charge"

    def test_skips_when_target_name_collides_with_live_table(self) -> None:
        # If a live table already holds the correct name, leave the buggy one for manual resolution.
        source = self._source("Stripe")
        _, buggy = self._schema_with_table(
            source,
            name="CreditNote",
            s3_folder_name="credit_note",
            table_name="stripe_credit_note",
        )
        DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="stripe_creditnote",  # the target name, already taken by a live table
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://bucket/y/*",
            external_data_source=source,
        )
        self._run()
        buggy.refresh_from_db()
        assert buggy.name == "stripe_credit_note"  # untouched
