from posthog.test.base import BaseTest

from parameterized import parameterized

from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.serializers import SignalSourceConfigSerializer
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

RUNNING = ExternalDataSchema.Status.RUNNING
COMPLETED = ExternalDataSchema.Status.COMPLETED
FAILED = ExternalDataSchema.Status.FAILED


class TestSignalSourceConfigStatus(BaseTest):
    def _github_source_with_schemas(self, *schemas: tuple[str, str]) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team, source_type="Github", status="Running", prefix="github_"
        )
        for name, status in schemas:
            ExternalDataSchema.objects.create(team=self.team, source=source, name=name, status=status)

    def _status(self) -> str | None:
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceProduct.GITHUB,
            source_type=SignalSourceType.ISSUE,
            enabled=True,
        )
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
        self._github_source_with_schemas(*schemas)

        assert self._status() == expected

    def test_ignores_deleted_sources(self) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team, source_type="Github", status="Running", prefix="github_", deleted=True
        )
        ExternalDataSchema.objects.create(team=self.team, source=source, name="posthog/posthog.issues", status=RUNNING)

        assert self._status() is None
