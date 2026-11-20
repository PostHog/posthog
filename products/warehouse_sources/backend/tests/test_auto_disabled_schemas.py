import uuid
from datetime import datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.warehouse_sources.backend.facade.contracts import AutoDisabledSchemaFilter
from products.warehouse_sources.backend.facade.staff import (
    select_auto_disabled_schemas_for_staff,
    summarize_auto_disabled_schemas_for_staff,
)
from products.warehouse_sources.backend.logic.auto_disabled_schemas import error_group
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

SCHEMA_VIEWS = "products.warehouse_sources.backend.presentation.views.external_data_schema"
TIMEOUT_ERROR = "OperationalError: connection to server at 10.0.0.1, port 5432 failed: timeout expired"
AUTH_ERROR = "password authentication failed for user analytics"
# Stands for the second team, whose ID is known only once the test runs.
OTHER_TEAM = -1


class TestErrorGroup(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_error", None, ""),
            ("empty_error", "", ""),
            ("cut_at_first_word_with_digit", TIMEOUT_ERROR, "OperationalError: connection to server at"),
            ("no_digits_keeps_line", AUTH_ERROR, AUTH_ERROR),
            ("first_line_only", "SSL SYSCALL error: EOF detected\nTraceback ...", "SSL SYSCALL error: EOF detected"),
            (
                "digit_too_early_keeps_line",
                "HTTP 401: Unauthorized for this account",
                "HTTP 401: Unauthorized for this account",
            ),
            ("long_line_truncated", "x" * 200, "x" * 80),
        ]
    )
    def test_error_group(self, _name: str, error: str | None, expected: str) -> None:
        group = error_group(error)

        assert group == expected
        # The group doubles as the error filter, so it must find the error it came from.
        if error:
            assert group.lower() in error.lower()


class TestAutoDisabledSchemaQueries(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.other_team = Team.objects.create(organization=self.organization, name="Other team")
        self.sources: dict[tuple[int, str], ExternalDataSource] = {}

    def _source(self, team_id: int, source_type: str) -> ExternalDataSource:
        key = (team_id, source_type)
        if key not in self.sources:
            self.sources[key] = ExternalDataSource.objects.create(
                team_id=team_id,
                source_id=str(uuid.uuid4()),
                connection_id=str(uuid.uuid4()),
                status="Completed",
                source_type=source_type,
            )
        return self.sources[key]

    def _schema(
        self,
        name: str,
        *,
        team_id: int | None = None,
        source_type: str = "Postgres",
        error: str | None = TIMEOUT_ERROR,
        stopped_days_ago: float | None = 1,
        should_sync: bool = False,
        deleted: bool = False,
    ) -> ExternalDataSchema:
        team_id = team_id or self.team.pk
        return ExternalDataSchema.objects.create(
            team_id=team_id,
            source=self._source(team_id, source_type),
            name=name,
            should_sync=should_sync,
            deleted=deleted,
            latest_error=error,
            auto_disabled_at=self.now - timedelta(days=stopped_days_ago) if stopped_days_ago is not None else None,
        )

    def _seed(self) -> None:
        self._schema("pg_timeout")
        self._schema("pg_auth", error=AUTH_ERROR)
        self._schema("stripe_timeout", source_type="Stripe")
        self._schema("other_team", team_id=self.other_team.pk)
        self._schema("five_days_ago", stopped_days_ago=5)
        self._schema("twenty_days_ago", stopped_days_ago=20)
        # Never listed: the user turned these off, they are deleted, or they sync.
        self._schema("user_disabled", stopped_days_ago=None)
        self._schema("deleted", deleted=True)
        self._schema("syncing", should_sync=True)

    @parameterized.expand(
        [
            ("defaults", {}, {"pg_timeout", "pg_auth", "stripe_timeout", "other_team", "five_days_ago"}),
            ("three_days", {"days": 3}, {"pg_timeout", "pg_auth", "stripe_timeout", "other_team"}),
            (
                "thirty_days",
                {"days": 30},
                {"pg_timeout", "pg_auth", "stripe_timeout", "other_team", "five_days_ago", "twenty_days_ago"},
            ),
            ("source_type", {"source_type": "Stripe"}, {"stripe_timeout"}),
            ("error_any_case", {"error": "PASSWORD Authentication"}, {"pg_auth"}),
            ("team", {"team_id": OTHER_TEAM}, {"other_team"}),
            (
                "source_type_and_error",
                {"source_type": "Postgres", "error": "timeout expired"},
                {"pg_timeout", "other_team", "five_days_ago"},
            ),
            ("no_match", {"source_type": "Stripe", "error": "password"}, set()),
        ]
    )
    def test_filters(self, _name: str, filters: dict, expected: set[str]) -> None:
        self._seed()
        if filters.get("team_id") == OTHER_TEAM:
            filters = {**filters, "team_id": self.other_team.pk}

        selection = select_auto_disabled_schemas_for_staff(AutoDisabledSchemaFilter(**{"days": 7, **filters}))

        assert {row.name for row in selection.rows} == expected
        assert selection.total == len(expected)

    def test_summary_counts_and_groups(self) -> None:
        self._seed()

        summary = summarize_auto_disabled_schemas_for_staff(AutoDisabledSchemaFilter(days=7))

        assert (summary.total, summary.team_count, summary.source_count, summary.grouped_count) == (5, 2, 3, 5)
        groups = {(group.source_type, group.error): group for group in summary.groups}
        assert set(groups) == {
            ("Postgres", "OperationalError: connection to server at"),
            ("Postgres", AUTH_ERROR),
            ("Stripe", "OperationalError: connection to server at"),
        }
        timeouts = groups[("Postgres", "OperationalError: connection to server at")]
        assert timeouts.count == 3
        assert summary.groups[0] == timeouts
        assert _close(timeouts.newest_at, self.now - timedelta(days=1))
        assert _close(timeouts.oldest_at, self.now - timedelta(days=5))

    @parameterized.expand(
        [
            ("turns_syncing_off", {"should_sync": False}, False),
            ("changes_another_field", {"sync_frequency": "6hour"}, True),
        ]
    )
    def test_customer_turning_syncing_off_takes_the_schema_out_of_the_picker(
        self, _name: str, payload: dict, still_listed: bool
    ) -> None:
        schema = self._schema("pg_timeout")
        self.client.force_login(self.user)

        with (
            patch(f"{SCHEMA_VIEWS}.external_data_workflow_exists", return_value=False),
            patch(f"{SCHEMA_VIEWS}.sync_external_data_job_workflow"),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                payload,
                content_type="application/json",
            )

        assert response.status_code == 200, response.content
        selection = select_auto_disabled_schemas_for_staff(AutoDisabledSchemaFilter(days=7))
        assert [row.name for row in selection.rows] == (["pg_timeout"] if still_listed else [])


def _close(actual: datetime, expected: datetime) -> bool:
    return abs(actual - expected) < timedelta(seconds=1)
