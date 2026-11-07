from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.event_definitions.backend.models import EventDefinitionMetadata, PropertyDefinitionMetadata

from ee.models.event_definition import EnterpriseEventDefinition
from ee.models.property_definition import EnterprisePropertyDefinition

_KINDS = [
    ("event", EnterpriseEventDefinition, EventDefinitionMetadata),
    ("property", EnterprisePropertyDefinition, PropertyDefinitionMetadata),
]


class TestDefinitionMetadataCopy(BaseTest):
    def _metadata(self, metadata_model, definition_id, team_id=None):
        return metadata_model.objects.for_team(team_id or self.team.id, canonical=True).get(pk=definition_id)

    @parameterized.expand(_KINDS)
    def test_saving_a_definition_copies_every_metadata_column(self, kind, enterprise_model, metadata_model):
        extra = {"owner": self.user, "default_columns": ["event", "person"]} if kind == "event" else {}
        with self.captureOnCommitCallbacks(execute=True):
            definition = enterprise_model.objects.create(
                team=self.team,
                name="signed_up",
                description="A user finished sign up",
                updated_by=self.user,
                verified=True,
                verified_at=timezone.now(),
                verified_by=self.user,
                hidden=False,
                **extra,
            )

        stored = enterprise_model.objects.get(pk=definition.pk)
        metadata = self._metadata(metadata_model, definition.pk)
        copied_columns = [field.attname for field in metadata_model._meta.concrete_fields if not field.primary_key]
        assert {column: getattr(metadata, column) for column in copied_columns} == {
            column: getattr(stored, column) for column in copied_columns
        }

    def test_a_partial_save_copies_the_stored_row_not_the_stale_instance(self):
        with self.captureOnCommitCallbacks(execute=True):
            definition = EnterpriseEventDefinition.objects.create(team=self.team, name="signed_up")
            stale = EnterpriseEventDefinition.objects.get(pk=definition.pk)
            other = EnterpriseEventDefinition.objects.get(pk=definition.pk)
            other.description = "Changed in another request"
            other.save()

            stale.verified = True
            stale.save(update_fields=["verified"])

        metadata = self._metadata(EventDefinitionMetadata, definition.pk)
        assert (metadata.description, metadata.verified) == ("Changed in another request", True)

    def test_metadata_keeps_the_team_of_a_definition_in_a_child_environment(self):
        child = Team.objects.create(organization=self.organization, name="Staging", parent_team=self.team)
        with self.captureOnCommitCallbacks(execute=True):
            definition = EnterpriseEventDefinition.objects.create(
                team=child, project_id=self.team.project_id, name="signed_up"
            )

        assert self._metadata(EventDefinitionMetadata, definition.pk, team_id=child.id).team_id == child.id

    def test_a_failed_copy_does_not_fail_the_edit(self):
        with connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE {EventDefinitionMetadata._meta.db_table} RENAME TO event_definitions_metadata_gone"
            )

        with (
            patch("products.event_definitions.backend.logic.definition_metadata.capture_exception") as capture,
            self.captureOnCommitCallbacks(execute=True),
        ):
            definition = EnterpriseEventDefinition.objects.create(team=self.team, name="signed_up", description="Kept")

        assert EnterpriseEventDefinition.objects.get(pk=definition.pk).description == "Kept"
        capture.assert_called_once()

    @parameterized.expand(_KINDS)
    def test_backfill_copies_earlier_rows_in_batches_and_resumes(self, kind, enterprise_model, metadata_model):
        ids = sorted(str(enterprise_model.objects.create(team=self.team, name=f"name_{i}").pk) for i in range(3))

        def copied_ids() -> list[str]:
            scoped = metadata_model.objects.for_team(self.team.id, canonical=True)
            return sorted(str(pk) for pk in scoped.values_list("pk", flat=True))

        options = {"kind": kind, "batch_size": 2, "sleep_seconds": 0, "stdout": StringIO()}
        call_command("backfill_definition_metadata", max_batches=1, **options)
        assert copied_ids() == ids[:2]

        call_command("backfill_definition_metadata", start_after=ids[1], **options)
        assert copied_ids() == ids

        rerun = StringIO()
        call_command("backfill_definition_metadata", **{**options, "stdout": rerun})
        assert "0 rows changed" in rerun.getvalue().splitlines()[-1]
