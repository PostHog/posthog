import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import status

from products.error_tracking.backend.models import ErrorTrackingMigration

VIEW_MODULE = "products.error_tracking.backend.presentation.views.source_migrations"


def _sentry_source(source_id=None):
    return MagicMock(id=source_id or uuid.uuid4(), source_type="Sentry")


class TestErrorTrackingMigrationsAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/error_tracking/migrations/{suffix}"

    def _create_migration(self, team=None, **overrides) -> ErrorTrackingMigration:
        team = team or self.team
        defaults = {
            "created_by": self.user,
            "source_type": ErrorTrackingMigration.SourceType.SENTRY,
            "external_data_source_id": uuid.uuid4(),
            "config": {"org_slug": "acme"},
            "status": ErrorTrackingMigration.Status.IMPORTING,
        }
        defaults.update(overrides)
        return ErrorTrackingMigration.objects.for_team(team.id).create(team=team, **defaults)

    @patch(f"{VIEW_MODULE}.start_migration_workflow", new_callable=AsyncMock)
    @patch(f"{VIEW_MODULE}.warehouse_api.get_source")
    def test_create_starts_workflow(self, mock_get_source, mock_start):
        source_id = uuid.uuid4()
        mock_get_source.return_value = _sentry_source(source_id)
        mock_start.return_value = ("wf-123", "run-456")

        response = self.client.post(
            self._url(),
            {
                "source_type": "sentry",
                "external_data_source_id": str(source_id),
                "config": {
                    "org_slug": "acme",
                    "date_from": "2026-01-01T00:00:00Z",
                    "issue_statuses": ["unresolved", "resolved"],
                },
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        migration = ErrorTrackingMigration.objects.for_team(self.team.id).get(id=response.json()["id"])
        assert migration.team_id == self.team.id
        assert migration.created_by == self.user
        assert migration.source_type == ErrorTrackingMigration.SourceType.SENTRY
        assert migration.config["org_slug"] == "acme"
        assert migration.workflow_id == "wf-123"
        assert migration.config["issue_statuses"] == ["unresolved", "resolved"]
        assert isinstance(migration.config["date_from"], str)
        mock_start.assert_awaited_once_with(migration_id=str(migration.id), team_id=self.team.id)

    @patch(f"{VIEW_MODULE}.warehouse_api.get_source")
    def test_create_rejects_config_failing_adapter_validation(self, mock_get_source):
        mock_get_source.return_value = _sentry_source()

        response = self.client.post(
            self._url(),
            {"source_type": "sentry", "external_data_source_id": str(uuid.uuid4()), "config": {}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "organization slug" in str(response.json())
        assert ErrorTrackingMigration.objects.unscoped().count() == 0

    @patch(f"{VIEW_MODULE}.warehouse_api.get_source")
    def test_create_rejects_source_type_mismatch(self, mock_get_source):
        mock_get_source.return_value = MagicMock(id=uuid.uuid4(), source_type="Stripe")

        response = self.client.post(
            self._url(),
            {"source_type": "sentry", "external_data_source_id": str(uuid.uuid4()), "config": {"org_slug": "acme"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert ErrorTrackingMigration.objects.unscoped().count() == 0

    @patch(f"{VIEW_MODULE}.warehouse_api.get_source")
    def test_create_rejects_second_active_migration(self, mock_get_source):
        mock_get_source.return_value = _sentry_source()
        self._create_migration()

        response = self.client.post(
            self._url(),
            {"source_type": "sentry", "external_data_source_id": str(uuid.uuid4()), "config": {"org_slug": "acme"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already running" in response.json()["detail"]

    @patch(f"{VIEW_MODULE}._cancel_workflow", new_callable=AsyncMock)
    def test_cancel_running_migration(self, mock_cancel):
        migration = self._create_migration(workflow_id="wf-123")

        response = self.client.post(self._url(f"{migration.id}/cancel/"))

        assert response.status_code == status.HTTP_200_OK
        migration.refresh_from_db()
        assert migration.status == ErrorTrackingMigration.Status.CANCELLED
        mock_cancel.assert_awaited_once_with("wf-123")

    def test_cancel_rejects_terminal_migration(self):
        migration = self._create_migration(status=ErrorTrackingMigration.Status.COMPLETED)

        response = self.client.post(self._url(f"{migration.id}/cancel/"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_attach_code_migration(self):
        migration = self._create_migration()
        task_id = uuid.uuid4()

        response = self.client.post(
            self._url(f"{migration.id}/attach_code_migration/"), {"task_id": str(task_id)}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        migration.refresh_from_db()
        assert migration.code_migration_task_id == task_id

    def test_list_and_retrieve_are_team_scoped(self):
        mine = self._create_migration()
        other_team = self.organization.teams.create(name="other")
        other = ErrorTrackingMigration.objects.for_team(other_team.id).create(
            team=other_team, external_data_source_id=uuid.uuid4(), config={"org_slug": "other"}
        )

        list_response = self.client.get(self._url())
        assert list_response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in list_response.json()["results"]]
        assert str(mine.id) in ids
        assert str(other.id) not in ids

        assert self.client.get(self._url(f"{other.id}/")).status_code == status.HTTP_404_NOT_FOUND
