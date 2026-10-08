from typing import Any

from posthog.test.base import TestMigrations


class TestRepinLangfuseApiVersionV3(TestMigrations):
    migrate_from = "0180_repin_incident_io_api_version_v3"
    migrate_to = "0181_repin_langfuse_api_version_v3"

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
                    api_version="v1" if name == "scores" else None,
                )
            return str(created.id)

        self.expected = {
            source("Langfuse", "v1", [("observations", True, False), ("traces", False, False)]): "v3",
            source("Langfuse", "v2", [("scores", True, False), ("sessions", True, True)]): "v3",
            source("Langfuse", "v2", [("observations", True, False), ("traces", True, False)]): "v2",
            source("Langfuse", "v1", [("sessions", True, False)]): "v1",
            source("Langfuse", "v1", [("traces", True, None)]): "v1",
            source("Langfuse", None, [("traces", False, False)]): None,
            source("Langfuse", "v3", []): "v3",
            source("Ably", "v1", []): "v1",
        }

    def test_repins_only_sources_that_lose_no_synced_table(self) -> None:
        assert self.apps is not None
        ExternalDataSource = self.apps.get_model("warehouse_sources", "ExternalDataSource")
        ExternalDataSchema = self.apps.get_model("warehouse_sources", "ExternalDataSchema")

        pins = dict(ExternalDataSource.objects.filter(id__in=self.expected).values_list("id", "api_version"))
        assert {str(source_id): pin for source_id, pin in pins.items()} == self.expected
        assert ExternalDataSchema.objects.get(name="scores").api_version == "v1"
