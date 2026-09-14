import uuid
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from products.tasks.backend.logic.services.gateway_usage import (
    GatewayUsageError,
    finish_gateway_usage_epoch,
    get_task_run_spend,
    get_task_spend,
    record_gateway_usage_request,
    refresh_task_run_spend,
    register_gateway_credential,
    settle_gateway_usage_request,
    start_gateway_usage_epoch,
)
from products.tasks.backend.logic.services.sandbox_pricing import COMPUTE_RATE_CARDS
from products.tasks.backend.models import GatewayUsageRequest, SandboxSession, Task, TaskRun


class TestGatewayUsage(APIBaseTest):
    def _run(self, *, status: str = TaskRun.Status.IN_PROGRESS) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="gateway accounting",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        return TaskRun.objects.create(task=task, team=self.team, status=status)

    def _receipt(self, bearer: str, *, cost: int = 15_000) -> dict[str, object]:
        return {
            "credential_id": hashlib.sha256(bearer.encode()).hexdigest(),
            "cost_microusd": cost,
            "model": "example-model",
            "provider": "example-provider",
            "input_tokens": 4,
            "output_tokens": 2,
            "cache_read_tokens": 1,
            "cache_write_tokens": 0,
            "settled_at": "2026-01-01T00:00:00+00:00",
        }

    def _settle(
        self, *, run: TaskRun, epoch_id: uuid.UUID, attempt_id: uuid.UUID, request_id: str, receipt: dict[str, object]
    ) -> tuple[bool, object]:
        response = SimpleNamespace(status_code=200, json=lambda: {**receipt, "request_id": request_id})
        with (
            override_settings(
                SANDBOX_AI_GATEWAY_URL="https://gateway.example/v1", SANDBOX_AI_GATEWAY_MINT_KEY="mint-key"
            ),
            patch("products.tasks.backend.logic.services.gateway_usage.requests.get", return_value=response),
        ):
            return settle_gateway_usage_request(
                run_id=run.id,
                team_id=self.team.id,
                epoch_id=epoch_id,
                attempt_id=attempt_id,
                request_id=request_id,
            )

    def _record_settled_request(
        self,
        *,
        run: TaskRun,
        bearer: str,
        epoch_id: uuid.UUID,
        request_id: str,
        cost: int = 15_000,
    ) -> uuid.UUID:
        attempt_id = uuid.uuid4()
        record_gateway_usage_request(
            run_id=run.id,
            team_id=self.team.id,
            epoch_id=epoch_id,
            attempt_id=attempt_id,
            request_id=request_id,
        )
        settled, _spend = self._settle(
            run=run,
            epoch_id=epoch_id,
            attempt_id=attempt_id,
            request_id=request_id,
            receipt=self._receipt(bearer, cost=cost),
        )
        assert settled is True
        return attempt_id

    def _session(
        self,
        *,
        run: TaskRun,
        sandbox_id: str,
        user_attributed_at: datetime | None,
        ended_at: datetime | None,
        cpu_request_cores: float | None = None,
        memory_request_mb: int | None = None,
    ) -> SandboxSession:
        now = timezone.now()
        return SandboxSession.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            task_run=run,
            sandbox_id=sandbox_id,
            cpu_cores=1,
            memory_gb=1,
            ttl_seconds=24 * 60 * 60,
            ttl_expires_at=now + timedelta(days=1),
            user_attributed_at=user_attributed_at,
            ended_at=ended_at,
            cpu_request_cores=cpu_request_cores,
            memory_request_mb=memory_request_mb,
        )

    def test_rotated_credentials_settle_prior_epoch_and_resume_new_epoch(self) -> None:
        run = self._run()
        old_bearer, new_bearer = "old-bearer", "new-bearer"
        prior_epoch, resumed_epoch = uuid.uuid4(), uuid.uuid4()
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer=old_bearer)
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=prior_epoch)
        prior_attempt = uuid.uuid4()
        record_gateway_usage_request(
            run_id=run.id,
            team_id=self.team.id,
            epoch_id=prior_epoch,
            attempt_id=prior_attempt,
            request_id="prior-request",
        )

        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer=new_bearer)
        settled, _spend = self._settle(
            run=run,
            epoch_id=prior_epoch,
            attempt_id=prior_attempt,
            request_id="prior-request",
            receipt=self._receipt(old_bearer),
        )
        assert settled is True
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=resumed_epoch)
        self._record_settled_request(
            run=run,
            bearer=new_bearer,
            epoch_id=resumed_epoch,
            request_id="resumed-request",
        )

        assert (
            GatewayUsageRequest.objects.for_team(self.team.id)
            .get(epoch__epoch_id=prior_epoch, attempt_id=prior_attempt)
            .settled_at
            is not None
        )
        assert refresh_task_run_spend(run_id=run.id, team_id=self.team.id).token_cost == 3

    def test_sealed_epoch_with_no_requests_reports_current_zero_token_cost(self) -> None:
        run = self._run()
        bearer = "example-bearer"
        epoch_id = uuid.uuid4()
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer=bearer)
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)

        spend = finish_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)

        assert spend.token_cost == 0
        assert spend.token_status == "current"

    def test_resuming_seals_prior_epoch_and_preserves_its_pending_status(self) -> None:
        run = self._run()
        epoch_id, resumed_epoch = uuid.uuid4(), uuid.uuid4()
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer="example-bearer")
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)
        record_gateway_usage_request(
            run_id=run.id,
            team_id=self.team.id,
            epoch_id=epoch_id,
            attempt_id=uuid.uuid4(),
            request_id="pending-request",
        )

        spend = start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=resumed_epoch)

        assert spend.token_status == "partial"
        assert (
            GatewayUsageRequest.objects.for_team(self.team.id).get(epoch__epoch_id=epoch_id).epoch.sealed_at is not None
        )

    def test_terminal_settled_token_cost_is_final_when_compute_is_unavailable(self) -> None:
        run = self._run(status=TaskRun.Status.COMPLETED)
        bearer = "example-bearer"
        epoch_id = uuid.uuid4()
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer=bearer)
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)
        self._record_settled_request(run=run, bearer=bearer, epoch_id=epoch_id, request_id="gateway-1")

        spend = finish_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)

        assert spend.token_status == "final"
        assert spend.compute_status == "unavailable"
        assert spend.is_final is False

    def test_pending_receipt_lookup_does_not_turn_unknown_cost_into_zero(self) -> None:
        run = self._run()
        epoch_id, attempt_id = uuid.uuid4(), uuid.uuid4()
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer="example-bearer")
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)
        record_gateway_usage_request(
            run_id=run.id,
            team_id=self.team.id,
            epoch_id=epoch_id,
            attempt_id=attempt_id,
            request_id="not-yet-settled",
        )
        response = SimpleNamespace(status_code=404, json=lambda: {})

        with (
            override_settings(
                SANDBOX_AI_GATEWAY_URL="https://gateway.example/v1", SANDBOX_AI_GATEWAY_MINT_KEY="mint-key"
            ),
            patch("products.tasks.backend.logic.services.gateway_usage.requests.get", return_value=response),
        ):
            settled, spend = settle_gateway_usage_request(
                run_id=run.id,
                team_id=self.team.id,
                epoch_id=epoch_id,
                attempt_id=attempt_id,
                request_id="not-yet-settled",
            )

        assert settled is False
        assert spend.token_cost is None
        assert spend.token_status == "partial"

    def test_duplicate_gateway_request_id_across_attempts_and_epochs_is_charged_once(self) -> None:
        run = self._run()
        bearer = "example-bearer"
        first_epoch, second_epoch = uuid.uuid4(), uuid.uuid4()
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer=bearer)
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=first_epoch)
        self._record_settled_request(run=run, bearer=bearer, epoch_id=first_epoch, request_id="gateway-1")
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=second_epoch)
        self._record_settled_request(run=run, bearer=bearer, epoch_id=second_epoch, request_id="gateway-1")

        assert refresh_task_run_spend(run_id=run.id, team_id=self.team.id).token_cost == 2

    def test_multiple_models_cache_tokens_and_zero_receipts_retain_gateway_costs(self) -> None:
        run = self._run()
        bearer = "example-bearer"
        epoch_id = uuid.uuid4()
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer=bearer)
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)
        for model, cost, cache_read, cache_write in (
            ("model-a", 4_500, 500, 20),
            ("model-b", 1_500, 30, 0),
            ("model-c", 0, 0, 0),
        ):
            attempt_id = uuid.uuid4()
            record_gateway_usage_request(
                run_id=run.id, team_id=self.team.id, epoch_id=epoch_id, attempt_id=attempt_id, request_id=model
            )
            receipt = {
                **self._receipt(bearer, cost=cost),
                "model": model,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
            }
            settled, _ = self._settle(
                run=run, epoch_id=epoch_id, attempt_id=attempt_id, request_id=model, receipt=receipt
            )
            assert settled
        rows = GatewayUsageRequest.objects.for_team(self.team.id).filter(task_run=run)
        assert sorted(rows.values_list("model", "cost_microusd", "cache_read_tokens", "cache_write_tokens")) == [
            ("model-a", 4_500, 500, 20),
            ("model-b", 1_500, 30, 0),
            ("model-c", 0, 0, 0),
        ]
        assert run.get_current_spend().token_cost == 1
        assert run.get_current_spend().token_status == "current"

    def test_out_of_order_request_after_epoch_seal_is_rejected(self) -> None:
        run = self._run()
        epoch_id = uuid.uuid4()
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer="example-bearer")
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)

        finish_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)
        with self.assertRaises(GatewayUsageError):
            record_gateway_usage_request(
                run_id=run.id,
                team_id=self.team.id,
                epoch_id=epoch_id,
                attempt_id=uuid.uuid4(),
                request_id="late-request",
            )

    def test_current_spend_getter_refreshes_stale_projection(self) -> None:
        run = self._run()
        epoch_id = uuid.uuid4()
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer="example-bearer")
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)
        run.state = {
            "spend": {
                "token_cost": 999,
                "compute_cost": None,
                "token_status": "current",
                "compute_status": "unavailable",
                "is_final": False,
            }
        }
        run.save(update_fields=["state"])

        spend = get_task_run_spend(run=run)

        assert spend.token_cost == 0
        assert spend.token_status == "current"

    def test_task_aggregate_uses_precise_sources_and_propagates_partial_unknown_status(self) -> None:
        bearer = "example-bearer"
        settled_run = self._run(status=TaskRun.Status.COMPLETED)
        pending_run = TaskRun.objects.create(task=settled_run.task, team=self.team)
        first_epoch, second_epoch = uuid.uuid4(), uuid.uuid4()
        for run, epoch_id in ((settled_run, first_epoch), (pending_run, second_epoch)):
            register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer=bearer)
            start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)
        self._record_settled_request(
            run=settled_run, bearer=bearer, epoch_id=first_epoch, request_id="settled", cost=15_000
        )
        self._record_settled_request(
            run=pending_run, bearer=bearer, epoch_id=second_epoch, request_id="pending-epoch", cost=15_000
        )
        record_gateway_usage_request(
            run_id=pending_run.id,
            team_id=self.team.id,
            epoch_id=second_epoch,
            attempt_id=uuid.uuid4(),
            request_id="still-pending",
        )

        spend = get_task_spend(team_id=self.team.id, task_id=settled_run.task_id)

        assert spend.token_cost == 3
        assert spend.token_status == "partial"
        assert spend.compute_cost is None
        assert spend.compute_status == "unavailable"

    def test_terminal_compute_cost_freezes_then_reopens_when_a_new_epoch_starts(self) -> None:
        run = self._run()
        bearer = "example-bearer"
        epoch_id = uuid.uuid4()
        now = timezone.now()
        self._session(
            run=run,
            sandbox_id="closed-sandbox",
            user_attributed_at=now - timedelta(hours=2),
            ended_at=now - timedelta(hours=1),
        )
        register_gateway_credential(run_id=run.id, team_id=self.team.id, bearer=bearer)
        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)

        finish_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=epoch_id)
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        final_spend = refresh_task_run_spend(run_id=run.id, team_id=self.team.id)
        assert final_spend.compute_status == "final"
        changed_rates = tuple(replace(card, cpu_core_second_usd=Decimal("0.01")) for card in COMPUTE_RATE_CARDS)
        with patch("products.tasks.backend.logic.services.gateway_usage.COMPUTE_RATE_CARDS", changed_rates):
            assert refresh_task_run_spend(run_id=run.id, team_id=self.team.id).compute_cost == final_spend.compute_cost

        start_gateway_usage_epoch(run_id=run.id, team_id=self.team.id, epoch_id=uuid.uuid4())

        assert refresh_task_run_spend(run_id=run.id, team_id=self.team.id).compute_status == "current"

    def test_compute_uses_burst_resource_floors_and_excludes_unattributed_prewarm(self) -> None:
        now = timezone.now()
        prewarmed_run = self._run()
        baseline_run = self._run()
        burst_run = self._run()
        open_run = self._run()
        self._session(
            run=prewarmed_run,
            sandbox_id="prewarmed-sandbox",
            user_attributed_at=None,
            ended_at=now,
            cpu_request_cores=16,
            memory_request_mb=16 * 1024,
        )
        self._session(
            run=baseline_run,
            sandbox_id="closed-baseline-sandbox",
            user_attributed_at=now - timedelta(hours=3),
            ended_at=now - timedelta(hours=2),
        )
        self._session(
            run=burst_run,
            sandbox_id="closed-burst-sandbox",
            user_attributed_at=now - timedelta(hours=3),
            ended_at=now - timedelta(hours=2),
            cpu_request_cores=4,
            memory_request_mb=4 * 1024,
        )
        self._session(
            run=open_run,
            sandbox_id="open-burst-sandbox",
            user_attributed_at=now - timedelta(hours=2),
            ended_at=None,
            cpu_request_cores=4,
            memory_request_mb=4 * 1024,
        )

        prewarmed_spend = refresh_task_run_spend(run_id=prewarmed_run.id, team_id=self.team.id)
        baseline_spend = refresh_task_run_spend(run_id=baseline_run.id, team_id=self.team.id)
        burst_spend = refresh_task_run_spend(run_id=burst_run.id, team_id=self.team.id)
        open_spend = refresh_task_run_spend(run_id=open_run.id, team_id=self.team.id)

        assert prewarmed_spend.compute_cost == 0
        assert burst_spend.compute_cost is not None
        assert baseline_spend.compute_cost is not None
        assert burst_spend.compute_cost > baseline_spend.compute_cost
        assert open_spend.compute_status == "current"
