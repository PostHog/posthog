from typing import get_args

from unittest.mock import patch

from django.utils import timezone

from posthog.models.activity_logging.activity_log import ActivityScope, field_exclusions
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.signals import model_activity_signal
from posthog.test.activity_log_utils import ActivityLogTestHelper

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource


class TestExternalDataSchemaActivityLogging(ActivityLogTestHelper):
    def test_external_data_schema_model_has_activity_mixin(self):
        self.assertTrue(issubclass(ExternalDataSchema, ModelActivityMixin))

    def test_external_data_schema_field_exclusions_configured(self):
        external_data_schema_exclusions = field_exclusions.get("ExternalDataSchema", [])

        self.assertIn("sync_type_config", external_data_schema_exclusions)
        self.assertIn("latest_error", external_data_schema_exclusions)
        self.assertIn("last_synced_at", external_data_schema_exclusions)
        self.assertIn("status", external_data_schema_exclusions)
        self.assertIn("table", external_data_schema_exclusions)
        self.assertIn("destination_links", external_data_schema_exclusions)
        self.assertIn("auto_disabled_at", external_data_schema_exclusions)
        self.assertIn("next_full_refresh_at", external_data_schema_exclusions)
        self.assertEqual(len(external_data_schema_exclusions), 8)

    def test_external_data_schema_scope_in_activity_log_types(self):
        self.assertIn("ExternalDataSchema", get_args(ActivityScope))

    def test_external_data_schema_creation_activity_logging(self):
        external_data_source = self.create_external_data_source()

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        assert schema is not None

        # Verify that no creation logs are created
        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 0)

    def test_external_data_schema_update_activity_logging(self):
        external_data_source = self.create_external_data_source()

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        assert schema is not None

        self.clear_activity_logs()

        self.update_external_data_schema(str(schema.id), {"should_sync": False})

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        self.assertEqual(log_entry.activity, "updated")
        self.assertEqual(log_entry.scope, "ExternalDataSchema")

    def test_external_data_schema_deletion_activity_logging(self):
        external_data_source = self.create_external_data_source()

        # Get the created schema from the source

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        assert schema is not None
        schema_id = str(schema.id)

        self.clear_activity_logs()

        self.delete_external_data_schema(schema_id)

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", schema_id)
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        self.assertEqual(log_entry.activity, "updated")
        self.assertEqual(log_entry.scope, "ExternalDataSchema")

        # Check that deletion is tracked via deleted field change
        detail_changes = log_entry.detail.get("changes", [])
        deleted_change = next((change for change in detail_changes if change.get("field") == "deleted"), None)
        self.assertIsNotNone(deleted_change)
        assert deleted_change is not None
        self.assertEqual(deleted_change["after"], True)

    def test_enabling_an_auto_disabled_schema_logs_only_the_enabled_change(self):
        external_data_source = self.create_external_data_source()

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        assert schema is not None

        ExternalDataSchema.objects.filter(pk=schema.pk).update(should_sync=False, auto_disabled_at=timezone.now())
        self.clear_activity_logs()

        disabled_schema = ExternalDataSchema.objects.get(pk=schema.pk)
        disabled_schema.should_sync = True
        disabled_schema.save()

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 1)

        changes = activity_logs[0].detail.get("changes", [])
        self.assertEqual([change["field"] for change in changes], ["enabled"])

    def test_logging_an_update_reads_source_and_team_in_one_query(self):
        external_data_source = self.create_external_data_source()
        schema_id = ExternalDataSchema.objects.filter(source_id=external_data_source["id"]).values_list(
            "id", flat=True
        )[0]
        schema = ExternalDataSchema.objects.get(id=schema_id)

        with patch("products.warehouse_sources.backend.activity_logging.log_activity") as log_activity:
            for expected_queries in (1, 0):
                with self.assertNumQueries(expected_queries):
                    model_activity_signal.send(
                        sender=ExternalDataSchema,
                        scope="ExternalDataSchema",
                        before_update=None,
                        after_update=schema,
                        activity="updated",
                        user=self.user,
                    )

                assert log_activity.call_args.kwargs["organization_id"] == self.organization.id
                context = log_activity.call_args.kwargs["detail"].context
                assert (context.source_id, context.source_type) == (str(external_data_source["id"]), "Stripe")

    def test_external_data_schema_relationship_logging(self):
        external_data_source = self.create_external_data_source()

        source_obj = ExternalDataSource.objects.get(id=external_data_source["id"])
        schema = source_obj.schemas.first()
        assert schema is not None

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 0)

        self.update_external_data_schema(str(schema.id), {"should_sync": False})

        activity_logs = self.get_activity_logs_for_item("ExternalDataSchema", str(schema.id))
        self.assertEqual(len(activity_logs), 1)

        log_entry = activity_logs[0]
        self.assertEqual(log_entry.activity, "updated")

        context = log_entry.detail.get("context")
        self.assertIsNotNone(context)
        self.assertEqual(context.get("source_id"), str(source_obj.id))
        self.assertEqual(context.get("source_type"), "Stripe")
