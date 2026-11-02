from typing import Any

from posthog.test.base import TestMigrations


class TestRepinLovableApiVersion20260911(TestMigrations):
    migrate_from = "0188_reset_trunkio_v2_failing_tests"
    migrate_to = "0189_repin_lovable_api_version_2026_09_11"

    def setUpBeforeMigration(self, apps: Any) -> None:
        ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
        ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

        def source(source_type: str, api_version: str | None, schemas: list[tuple[str, bool, bool | None]]) -> str:
            created = ExternalDataSource.objects.create(
                team_id=self.team.id,
                source_id="source-id",
                connection_id="connection-id",
                status="Completed",
                source_type=source_type,
                api_version=api_version,
            )
            for name, should_sync, deleted in schemas:
                ExternalDataSchema.objects.create(
                    team_id=self.team.id,
                    source=created,
                    name=name,
                    should_sync=should_sync,
                    deleted=deleted,
                    api_version="v1" if name == "ProjectPiiLabels" else None,
                )
            return str(created.id)

        self.expected = {
            source("Lovable", "v1", [("Workspaces", True, False), ("WorkspaceCreditHistory", True, False)]): (
                "2026-09-11"
            ),
            source("Lovable", "v1", [("ProjectPiiLabels", True, False), ("ProjectCollaborators", False, False)]): (
                "2026-09-11"
            ),
            source("Lovable", "v1", [("ProjectCollaborators", True, True)]): "2026-09-11",
            source("Lovable", "v1", [("ProjectCollaborators", True, False)]): "v1",
            source("Lovable", "v1", [("ProjectCollaborators", True, None)]): "v1",
            source("Lovable", None, [("Workspaces", True, False)]): None,
            source("Lovable", "2026-09-11", []): "2026-09-11",
            source("Langfuse", "v1", []): "v1",
        }

    def test_repins_only_sources_that_lose_no_synced_table(self) -> None:
        assert self.apps is not None
        ExternalDataSource = self.apps.get_model("warehouse_sources", "ExternalDataSource")
        ExternalDataSchema = self.apps.get_model("warehouse_sources", "ExternalDataSchema")

        pins = dict(ExternalDataSource.objects.filter(id__in=self.expected).values_list("id", "api_version"))
        assert {str(source_id): pin for source_id, pin in pins.items()} == self.expected
        assert ExternalDataSchema.objects.get(name="ProjectPiiLabels").api_version == "v1"
