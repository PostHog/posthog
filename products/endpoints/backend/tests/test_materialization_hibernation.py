from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest import mock

from django.utils import timezone

from parameterized import parameterized
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.schema import EndpointRunRequest

from posthog.clickhouse.query_tagging import tag_queries
from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.endpoints.backend.logic.execution import EndpointExecutionService
from products.endpoints.backend.models import EndpointVersion
from products.endpoints.backend.notifications import _EndpointViewers
from products.endpoints.backend.rate_limit import is_endpoint_materialization_ready, set_endpoint_materialization_ready
from products.endpoints.backend.tasks.tasks import deactivate_stale_materializations, wake_hibernated_materialization
from products.endpoints.backend.tests.conftest import create_endpoint_with_version
from products.notifications.backend.facade.api import TargetType


class TestMaterializationHibernation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.endpoint = create_endpoint_with_version(
            name="daily_totals",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS total"},
            created_by=self.user,
        )
        self.version = self.endpoint.get_version()
        self.run_url = f"/api/projects/{self.team.pk}/endpoints/{self.endpoint.name}/run/"
        self.detail_url = f"/api/projects/{self.team.pk}/endpoints/{self.endpoint.name}/"
        self.api_key = self.create_personal_api_key_with_scopes(["endpoint:read"])
        self.query_patcher = mock.patch(
            "products.endpoints.backend.logic.execution.process_query_model",
            return_value={"results": [[1]], "columns": ["total"], "types": ["UInt8"]},
        )
        self.query_patcher.start()
        self.addCleanup(self.query_patcher.stop)

    def test_never_called_version_hibernates_and_wakes_on_api_key_execution(self) -> None:
        old = timezone.now() - timedelta(days=45)
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=self.version.materialized_view_name,
            query=self.version.query,
            is_materialized=True,
            last_run_at=timezone.now(),
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        DataWarehouseSavedQuery.objects.filter(pk=saved_query.pk).update(created_at=old)
        EndpointVersion.objects.filter(pk=self.version.pk).update(saved_query=saved_query, created_at=old)
        set_endpoint_materialization_ready(self.team.pk, self.endpoint.name, True, version=1)

        with mock.patch("products.endpoints.backend.notifications.create_notification") as notify:
            deactivate_stale_materializations()

        self.version.refresh_from_db()
        assert self.version.materialization_hibernated_at is not None
        assert self.version.saved_query_id is None
        assert is_endpoint_materialization_ready(self.team.pk, self.endpoint.name, version=1) is None
        saved_query.refresh_from_db()
        assert saved_query.deleted and not saved_query.is_materialized
        notify.assert_called_once()
        assert notify.call_args.args[0].resource_id == str(self.endpoint.pk)

        with mock.patch("products.endpoints.backend.logic.execution.wake_hibernated_materialization.delay") as dispatch:
            response = self.client.get(self.run_url, headers={"authorization": f"Bearer {self.api_key}"})
        assert response.status_code == 200, response.content
        assert response.json()["results"] == [[1]]
        dispatch.assert_called_once()
        self.version.refresh_from_db()
        assert self.version.materialization_hibernated_at is None
        assert self.version.last_executed_at is not None

        with mock.patch.object(DataWarehouseSavedQuery, "schedule_materialization"):
            wake_hibernated_materialization(*dispatch.call_args.args)
        self.version.refresh_from_db()
        assert self.version.saved_query is not None
        assert self.version.saved_query.is_materialized
        assert self.version.saved_query_id != saved_query.pk
        assert self.version.materialization_hibernated_at is None
        assert ActivityLog.objects.filter(activity="materialization_enabled", user__isnull=True).exists()

    @parameterized.expand(["session", "user_disabled", "endpoint_deactivated", "version_deactivated"])
    def test_user_actions_do_not_request_a_wake(self, action: str) -> None:
        EndpointVersion.objects.filter(pk=self.version.pk).update(materialization_hibernated_at=timezone.now())
        if action != "session":
            payload = {"is_materialized": False} if action == "user_disabled" else {"is_active": False}
            url = self.detail_url + ("?version=1" if action == "version_deactivated" else "")
            response = self.client.patch(url, payload, format="json")
            assert response.status_code == 200, response.content
            self.version.refresh_from_db()
            assert self.version.materialization_hibernated_at is None

        with mock.patch("products.endpoints.backend.logic.execution.wake_hibernated_materialization.delay") as dispatch:
            headers = {} if action == "session" else {"authorization": f"Bearer {self.api_key}"}
            response = self.client.get(self.run_url, headers=headers)
        expected_status = {"endpoint_deactivated": 404, "version_deactivated": 400}.get(action, 200)
        assert response.status_code == expected_status, response.content
        dispatch.assert_not_called()
        self.version.refresh_from_db()
        if action == "session":
            assert self.version.last_executed_at is None
            assert self.version.materialization_hibernated_at is not None

    def test_calls_with_the_same_hibernation_snapshot_dispatch_once(self) -> None:
        EndpointVersion.objects.filter(pk=self.version.pk).update(materialization_hibernated_at=timezone.now())
        snapshots = [EndpointVersion.objects.get(pk=self.version.pk) for _ in range(2)]
        request = Request(APIRequestFactory().get(self.run_url))
        request.user = self.user
        service = EndpointExecutionService(self.team, request)
        with mock.patch("products.endpoints.backend.logic.execution.wake_hibernated_materialization.delay") as dispatch:
            for snapshot in snapshots:
                tag_queries(access_method="personal_api_key")
                response = service.execute(self.endpoint, EndpointRunRequest(), snapshot)
                assert response.status_code == 200
        dispatch.assert_called_once()

    @parameterized.expand(["rematerialized", "inactive", "unsupported", "user_disabled", "wrong_team"])
    def test_obsolete_wake_does_not_enable_materialization(self, change: str) -> None:
        claimed_updated_at = self.version.updated_at.isoformat()
        if change == "rematerialized":
            query = DataWarehouseSavedQuery.objects.create(team=self.team, name="existing", query=self.version.query)
            self.version.enable_materialization(query)
        elif change == "inactive":
            EndpointVersion.objects.filter(pk=self.version.pk).update(is_active=False)
        elif change == "unsupported":
            EndpointVersion.objects.filter(pk=self.version.pk).update(query={"kind": "FunnelsQuery"})
        elif change == "user_disabled":
            self.version.disable_materialization()
        team_id = self.team.pk + 1 if change == "wrong_team" else self.team.pk
        with mock.patch.object(DataWarehouseSavedQuery, "schedule_materialization") as schedule:
            wake_hibernated_materialization(team_id, str(self.version.pk), claimed_updated_at)
        schedule.assert_not_called()

    def test_failed_wake_leaves_inline_execution_available(self) -> None:
        with mock.patch.object(
            DataWarehouseSavedQuery, "schedule_materialization", side_effect=RuntimeError("offline")
        ):
            wake_hibernated_materialization(self.team.pk, str(self.version.pk), self.version.updated_at.isoformat())
        self.version.refresh_from_db()
        assert self.version.saved_query_id is None
        assert self.version.materialization_hibernated_at is None
        with mock.patch("products.endpoints.backend.logic.execution.wake_hibernated_materialization.delay") as dispatch:
            response = self.client.get(self.run_url, headers={"authorization": f"Bearer {self.api_key}"})
        assert response.status_code == 200, response.content
        dispatch.assert_not_called()

    def test_manual_resume_clears_hibernation(self) -> None:
        EndpointVersion.objects.filter(pk=self.version.pk).update(materialization_hibernated_at=timezone.now())
        with mock.patch.object(DataWarehouseSavedQuery, "schedule_materialization"):
            response = self.client.patch(self.detail_url, {"is_materialized": True}, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["materialization"]["hibernated"] is False
        self.version.refresh_from_db()
        assert self.version.saved_query is not None
        assert self.version.materialization_hibernated_at is None

    def test_notification_excludes_members_denied_the_endpoint(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        viewer = User.objects.create_and_join(self.organization, "viewer@example.com", "test-password")
        denied = User.objects.create_and_join(self.organization, "denied@example.com", "test-password")
        AccessControl.objects.create(
            team=self.team,
            resource="endpoint",
            resource_id=str(self.endpoint.pk),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=denied, organization=self.organization),
        )
        recipients = _EndpointViewers(self.endpoint).resolve(TargetType.TEAM, str(self.team.pk), self.team.pk)
        assert viewer.pk in recipients
        assert denied.pk not in recipients
