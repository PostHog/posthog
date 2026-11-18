from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError

from parameterized import parameterized

from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.serializers import SignalSourceConfigSerializer
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

RUNNING = ExternalDataSchema.Status.RUNNING
COMPLETED = ExternalDataSchema.Status.COMPLETED
FAILED = ExternalDataSchema.Status.FAILED


class TestSignalSourceConfigStatus(BaseTest):
    def _source_with_schemas(self, source_type: str, *schemas: tuple[str, str]) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=source_type, status="Running", prefix=f"{source_type.lower()}_"
        )
        for name, status in schemas:
            ExternalDataSchema.objects.create(team=self.team, source=source, name=name, status=status)

    def _config(self, source_product: str, source_type: str) -> SignalSourceConfig:
        return SignalSourceConfig.objects.create(
            team=self.team,
            source_product=source_product,
            source_type=source_type,
            enabled=True,
        )

    def _status(self) -> str | None:
        config = self._config(SignalSourceProduct.GITHUB, SignalSourceType.ISSUE)
        return SignalSourceConfigSerializer(config).data["status"]

    @parameterized.expand(
        [
            ("legacy_bare_row", [("issues", RUNNING)], "running"),
            ("qualified_row", [("posthog/posthog.issues", RUNNING)], "running"),
            ("repo_name_with_dots", [("posthog/some.repo.issues", COMPLETED)], "completed"),
            (
                "failing_repo_outranks_completed_sibling",
                [("posthog/a.issues", COMPLETED), ("posthog/b.issues", FAILED)],
                "failed",
            ),
            (
                "running_outranks_everything",
                [("posthog/a.issues", FAILED), ("posthog/b.issues", RUNNING)],
                "running",
            ),
            ("only_other_endpoints", [("posthog/posthog.pull_requests", RUNNING)], None),
            ("no_rows", [], None),
        ]
    )
    def test_status_across_repo_rows(self, _name: str, schemas: list[tuple[str, str]], expected: str | None) -> None:
        self._source_with_schemas("Github", *schemas)

        assert self._status() == expected

    def test_ignores_deleted_sources(self) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team, source_type="Github", status="Running", prefix="github_", deleted=True
        )
        ExternalDataSchema.objects.create(team=self.team, source=source, name="posthog/posthog.issues", status=RUNNING)

        assert self._status() is None

    def test_reports_no_status_when_the_warehouse_read_fails(self) -> None:
        self._source_with_schemas("Github", ("posthog/posthog.issues", RUNNING))
        configs = [
            self._config(SignalSourceProduct.GITHUB, SignalSourceType.ISSUE),
            self._config(SignalSourceProduct.LINEAR, SignalSourceType.ISSUE),
        ]

        with patch.object(
            ExternalDataSchema.objects, "filter", side_effect=OperationalError("statement timeout")
        ) as read:
            rows = SignalSourceConfigSerializer(configs, many=True).data

        assert [row["status"] for row in rows] == [None, None]
        # A failed read is cached, so a broken warehouse costs the list one query instead of one per row.
        assert read.call_count == 1

    def test_reads_every_source_status_in_one_query(self) -> None:
        # Github and Linear issues share the `issues` schema name, so a status read that keys on
        # the name alone would hand one source the other's badge.
        self._source_with_schemas("Github", ("posthog/posthog.issues", RUNNING))
        self._source_with_schemas("Linear", ("issues", COMPLETED))
        configs = [
            self._config(SignalSourceProduct.GITHUB, SignalSourceType.ISSUE),
            self._config(SignalSourceProduct.LINEAR, SignalSourceType.ISSUE),
            self._config(SignalSourceProduct.ZENDESK, SignalSourceType.TICKET),
        ]

        with self.assertNumQueries(1):
            rows = SignalSourceConfigSerializer(configs, many=True).data

        assert {row["source_product"]: row["status"] for row in rows} == {
            SignalSourceProduct.GITHUB: "running",
            SignalSourceProduct.LINEAR: "completed",
            SignalSourceProduct.ZENDESK: None,
        }
