import uuid
from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.db import OperationalError
from django.http import HttpResponse
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.utils import hash_key_value

from products.tasks.backend.models import Task, TaskRun


@override_settings(AI_GATEWAY_INTERNAL_TOKEN="gateway-token")
class TestTaskRunGatewayUsageAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.schedule_usage = self.enterContext(patch("products.tasks.backend.facade.gateway.schedule_gateway_usage"))

    def _run(
        self,
        *,
        team: Team | None = None,
        status_value: str = TaskRun.Status.IN_PROGRESS,
        environment: str = TaskRun.Environment.CLOUD,
    ) -> TaskRun:
        team = team or self.team
        task = Task.objects.create(
            team=team,
            created_by=self.user,
            title="Gateway usage task",
            description="Synthetic task",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        return TaskRun.objects.create(task=task, team=team, status=status_value, environment=environment)

    def _url(self, run: TaskRun, request_id: str = "request_1", *, team_id: int | None = None) -> str:
        return f"/internal/teams/{team_id or run.team_id}/task_runs/{run.id}/generation_requests/{request_id}/"

    def _post(
        self,
        run: TaskRun,
        request_id: str = "request_1",
        *,
        wallet_team_id: int | None = None,
        authorization: str = "Bearer gateway-token",
        data: object | None = None,
    ) -> HttpResponse:
        return APIClient().post(
            self._url(run, request_id),
            data,
            format="json",
            HTTP_AUTHORIZATION=authorization,
            HTTP_X_POSTHOG_GATEWAY_TEAM_ID=str(run.team_id if wallet_team_id is None else wallet_team_id),
        )

    def _mint_key_for(self, team: Team, token: str) -> None:
        ProjectSecretAPIKey.objects.create(
            team=team, label=f"mint-{uuid.uuid4().hex}", secure_value=hash_key_value(token)
        )

    @parameterized.expand([(TaskRun.Environment.CLOUD,), (TaskRun.Environment.LOCAL,)])
    def test_callback_accounts_only_cloud_runs_before_initialization(self, environment: str) -> None:
        run = self._run(environment=environment)
        updated_at = run.updated_at

        response = self._post(run)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        run.refresh_from_db()
        if environment == TaskRun.Environment.CLOUD:
            assert run.state == {"unprocessed_request_ids": ["request_1"], "token_spend": {}}
            self.schedule_usage.assert_called_once()
        else:
            assert run.state == {}
            assert run.updated_at == updated_at
            self.schedule_usage.assert_not_called()

    def test_callback_rejects_missing_or_invalid_service_credential(self) -> None:
        run = self._run()

        for authorization in ("", "Bearer wrong", "Bearer caf\u00e9"):
            response = self._post(run, authorization=authorization)
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

        run.refresh_from_db()
        assert run.state == {}

    @override_settings(AI_GATEWAY_INTERNAL_TOKEN="")
    def test_callback_rejects_an_unconfigured_service_token(self) -> None:
        run = self._run()
        assert self._post(run).status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand([("state_write",), ("scheduling",)])
    def test_callback_does_not_acknowledge_a_failed_write_or_schedule(self, failure: str) -> None:
        run = self._run()
        client = APIClient()
        client.raise_request_exception = False
        target = (
            "products.tasks.backend.logic.services.gateway_usage._save_accounting_state"
            if failure == "state_write"
            else "products.tasks.backend.facade.gateway.schedule_gateway_usage"
        )
        with patch(target, side_effect=OperationalError("unavailable")):
            response = client.post(
                self._url(run),
                {},
                format="json",
                HTTP_AUTHORIZATION="Bearer gateway-token",
                HTTP_X_POSTHOG_GATEWAY_TEAM_ID=str(run.team_id),
            )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        run.refresh_from_db()
        assert run.state == (
            {} if failure == "state_write" else {"unprocessed_request_ids": ["request_1"], "token_spend": {}}
        )
        assert self._post(run).status_code == status.HTTP_204_NO_CONTENT
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request_1"]

    def test_callback_requires_a_valid_wallet_and_request_identifiers(self) -> None:
        run = self._run()

        assert self._post(run, wallet_team_id=0).status_code == status.HTTP_400_BAD_REQUEST
        assert self._post(run, request_id="not a request ID").status_code == status.HTTP_400_BAD_REQUEST
        assert (
            APIClient()
            .post(
                self._url(run),
                {},
                format="json",
                HTTP_AUTHORIZATION="Bearer gateway-token",
            )
            .status_code
            == status.HTTP_400_BAD_REQUEST
        )

    @override_settings(SANDBOX_AI_GATEWAY_MINT_KEY="phs_callback_mint")
    def test_callback_allows_the_configured_mint_key_wallet_for_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Gateway wallet")
        self._mint_key_for(other_team, "phs_callback_mint")
        run = self._run()

        response = self._post(run, wallet_team_id=other_team.id)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request_1"]

    @override_settings(SANDBOX_AI_GATEWAY_MINT_KEY="phs_callback_mint")
    def test_callback_rejects_a_foreign_wallet(self) -> None:
        mint_team = Team.objects.create(organization=self.organization, name="Mint wallet")
        foreign_team = Team.objects.create(organization=self.organization, name="Foreign wallet")
        self._mint_key_for(mint_team, "phs_callback_mint")
        run = self._run()

        response = self._post(run, wallet_team_id=foreign_team.id)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        run.refresh_from_db()
        assert run.state == {}

    def test_callback_is_idempotent_before_and_after_processing_and_terminalization(self) -> None:
        run = self._run()

        assert self._post(run).status_code == status.HTTP_204_NO_CONTENT
        assert self._post(run).status_code == status.HTTP_204_NO_CONTENT
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request_1"]

        run.status = TaskRun.Status.COMPLETED
        run.state = {
            "unprocessed_request_ids": [],
            "token_spend": {"model": {"provider": {"spend_microusd": 4, "request_ids": ["request_1"]}}},
        }
        run.save(update_fields=["status", "state"])

        assert self._post(run).status_code == status.HTTP_204_NO_CONTENT
        run.refresh_from_db()
        assert run.status == TaskRun.Status.COMPLETED
        assert run.state["unprocessed_request_ids"] == []
        assert run.state["token_spend"]["model"]["provider"]["spend_microusd"] == 4
        assert self._post(run, "request_2").status_code == status.HTTP_204_NO_CONTENT
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request_2"]
        assert run.status == TaskRun.Status.COMPLETED

    def test_callback_returns_not_found_for_a_run_outside_the_path_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        run = self._run(team=other_team)

        response = APIClient().post(
            self._url(run, team_id=self.team.id),
            {},
            format="json",
            HTTP_AUTHORIZATION="Bearer gateway-token",
            HTTP_X_POSTHOG_GATEWAY_TEAM_ID=str(self.team.id),
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_ordinary_patch_cannot_write_queue_or_spend(self) -> None:
        run = self._run()
        run.state = {
            "unprocessed_request_ids": ["existing"],
            "token_spend": {"model": {"provider": {"spend_microusd": 4, "request_ids": ["existing"]}}},
            "token_spend_incomplete": True,
            "compute_spend": 2,
        }
        run.save(update_fields=["state"])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/tasks/{run.task_id}/runs/{run.id}/",
            {
                "state": {
                    "unprocessed_request_ids": ["forged"],
                    "token_spend": {},
                    "token_spend_incomplete": False,
                    "compute_spend": 999,
                },
                "state_append": {"unprocessed_request_ids": "forged"},
                "state_remove_keys": [
                    "unprocessed_request_ids",
                    "token_spend",
                    "token_spend_incomplete",
                    "compute_spend",
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"]["token_spend_incomplete"] is True
        run.refresh_from_db()
        assert run.state == {
            "unprocessed_request_ids": ["existing"],
            "token_spend": {"model": {"provider": {"spend_microusd": 4, "request_ids": ["existing"]}}},
            "token_spend_incomplete": True,
            "compute_spend": 2,
        }

    @parameterized.expand([(False, True), (True, True), (False, False)])
    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    @patch("products.tasks.backend.logic.services.gateway_usage._compute_spend_source", return_value=Decimal("0.12"))
    def test_terminal_patch_returns_spend_without_blocking_completion(
        self, refresh_fails: bool, uses_gateway: bool, compute_spend: Mock, signal: Mock
    ) -> None:
        run = self._run()
        run.state = {"unprocessed_request_ids": [], "token_spend": {}, "compute_spend": 7}
        if not uses_gateway:
            run.state = {"token_spend_incomplete": True, "compute_spend": 7}
        run.save(update_fields=["state"])
        if refresh_fails:
            compute_spend.side_effect = OperationalError("unavailable")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/tasks/{run.task_id}/runs/{run.id}/",
            {"status": TaskRun.Status.COMPLETED},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        run.refresh_from_db()
        assert response.json()["state"]["compute_spend"] == run.state["compute_spend"] == (7 if refresh_fails else 12)
        assert response.json()["updated_at"] == run.updated_at.isoformat().replace("+00:00", "Z")
        signal.assert_called_once_with(run.id, TaskRun.Status.COMPLETED, None)
