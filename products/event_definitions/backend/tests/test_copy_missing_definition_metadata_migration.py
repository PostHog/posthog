import importlib
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection

from parameterized import parameterized

from products.event_definitions.backend.logic.definition_metadata import copy_definition_metadata
from products.event_definitions.backend.models import EventDefinitionMetadata, PropertyDefinitionMetadata

from ee.models.event_definition import EnterpriseEventDefinition
from ee.models.property_definition import EnterprisePropertyDefinition

migration = importlib.import_module(
    "products.event_definitions.backend.migrations.0020_copy_missing_definition_metadata"
)


class TestCopyMissingDefinitionMetadataMigration(BaseTest):
    @parameterized.expand(
        [
            ("event", EnterpriseEventDefinition, EventDefinitionMetadata),
            ("property", EnterprisePropertyDefinition, PropertyDefinitionMetadata),
        ]
    )
    def test_copies_only_the_rows_without_metadata(self, kind, enterprise_model, metadata_model):
        missing = [
            enterprise_model.objects.create(team=self.team, name=f"missing_{i}", description="from ee", hidden=True)
            for i in range(2)
        ]
        copied = enterprise_model.objects.create(team=self.team, name="copied", description="from ee")
        copy_definition_metadata(kind, [copied.pk])
        metadata_model.all_teams.filter(pk=copied.pk).update(description="newer copy")

        with patch.object(migration, "BATCH_SIZE", 1):
            migration.copy_missing_definition_metadata(None, SimpleNamespace(connection=connection))

        scoped = metadata_model.objects.for_team(self.team.id, canonical=True)
        for definition in missing:
            metadata = scoped.get(pk=definition.pk)
            assert (metadata.team_id, metadata.description, metadata.hidden) == (self.team.id, "from ee", True)
        assert scoped.get(pk=copied.pk).description == "newer copy"
