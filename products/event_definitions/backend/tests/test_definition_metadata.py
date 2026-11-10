from functools import partial
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.db import OperationalError, connection, transaction
from django.utils import timezone

import psycopg.errors
from parameterized import parameterized

from posthog.models import Team

from products.event_definitions.backend.logic.definition_metadata import (
    batch_definition_metadata_copies,
    copy_definition_metadata,
)
from products.event_definitions.backend.models import EventDefinitionMetadata, PropertyDefinitionMetadata

from ee.models.event_definition import EnterpriseEventDefinition
from ee.models.property_definition import EnterprisePropertyDefinition

_KINDS = [
    ("event", EnterpriseEventDefinition, EventDefinitionMetadata),
    ("property", EnterprisePropertyDefinition, PropertyDefinitionMetadata),
]


def _django_deadlock_error() -> OperationalError:
    """A deadlock as Django raises it: its OperationalError wraps the psycopg error."""
    error = OperationalError("deadlock detected")
    error.__cause__ = psycopg.errors.DeadlockDetected("deadlock detected")
    return error


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

    def test_saves_in_a_batch_copy_in_one_statement_per_kind_after_the_commit(self):
        with (
            patch(
                "products.event_definitions.backend.logic.definition_metadata.copy_definition_metadata",
                wraps=copy_definition_metadata,
            ) as copy,
            self.captureOnCommitCallbacks(execute=True),
        ):
            with transaction.atomic(), batch_definition_metadata_copies():
                events = [EnterpriseEventDefinition.objects.create(team=self.team, name=f"e_{i}") for i in range(3)]
                prop = EnterprisePropertyDefinition.objects.create(team=self.team, name="plan")
                copy.assert_not_called()

        assert sorted((kind, len(ids)) for kind, ids in (call.args for call in copy.call_args_list)) == [
            ("event", 3),
            ("property", 1),
        ]
        assert self._metadata(PropertyDefinitionMetadata, prop.pk)
        assert all(self._metadata(EventDefinitionMetadata, event.pk) for event in events)

    @parameterized.expand(_KINDS)
    def test_django_reads_through_the_unscoped_manager(self, _kind, _enterprise_model, metadata_model):
        assert metadata_model._default_manager.name == "all_teams"

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

    @parameterized.expand(
        [
            ("deadlock", _django_deadlock_error(), 2, None),
            ("not transient", ValueError("bad batch"), 1, ValueError),
        ]
    )
    def test_backfill_retries_a_batch_only_after_a_transient_error(self, _name, error, calls, raised):
        EnterpriseEventDefinition.objects.create(team=self.team, name="signed_up")
        with patch(
            "products.event_definitions.backend.management.commands.backfill_definition_metadata.copy_definition_metadata",
            side_effect=[error, 1],
        ) as copy:
            run = partial(
                call_command, "backfill_definition_metadata", kind="event", sleep_seconds=0, stdout=StringIO()
            )
            if raised:
                with self.assertRaises(raised):
                    run()
            else:
                run()

        assert copy.call_count == calls
