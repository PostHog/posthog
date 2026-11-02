import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

import httpx
from parameterized import parameterized

from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import hash_key_value

from products.tasks.backend.logic.services.compute_settlement import (
    ComputeSettlementDeploymentError,
    SettlementOutcome,
    TeamComputeDelta,
    reconcile_compute_settlement,
    settle_overdue_sandbox_compute,
    settle_sandbox_session,
    settle_task_run_compute,
    unpark_sandbox_compute,
)
from products.tasks.backend.management.commands.reconcile_sandbox_compute_settlement import CENT_ROUNDING_TOLERANCE_USD
from products.tasks.backend.models import SandboxSession, Task, TaskClientProvenance, TaskRun

MINT_KEY = "phs_" + "c" * 35
GATEWAY_URL = "http://gateway.internal"
HTTPX_POST = "posthog.llm.gateway_internal_client.httpx.post"


def _response(status: int, body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body or {}, request=httpx.Request("POST", GATEWAY_URL))


def _ok(*, amount: str = "1.500000", entry_id: str = "entry-1", duplicate: bool = False) -> httpx.Response:
    return _response(200, {"team_id": 1, "entry_id": entry_id, "amount_usd": amount, "duplicate": duplicate})


@override_settings(
    GATEWAY_COMPUTE_DEBIT_ENABLED=True,
    SANDBOX_AI_GATEWAY_MINT_KEY=MINT_KEY,
    AI_GATEWAY_INTERNAL_URL=GATEWAY_URL,
    AI_GATEWAY_INTERNAL_TOKEN="operator-token",
)
class TestComputeSettlement(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        ProjectSecretAPIKey.objects.create(
            team=self.team, label="mint", secure_value=hash_key_value(MINT_KEY), scopes=["llm_gateway:read"]
        )

    def _session(self, *, with_actor: bool = True, **overrides: Any) -> SandboxSession:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
            created_by=self.user if with_actor else None,
        )
        run = TaskRun.objects.create(task=task, team=self.team, environment=TaskRun.Environment.CLOUD)
        created_at = overrides.pop("created_at", self.now - timedelta(hours=2))
        defaults: dict[str, Any] = {
            "team": self.team,
            "task_run": run,
            "sandbox_id": f"sb-{SandboxSession.objects.unscoped().count()}",
            "origin_product": Task.OriginProduct.USER_CREATED,
            "client_provenance": TaskClientProvenance.POSTHOG_DESKTOP,
            "cpu_cores": 4.0,
            "memory_gb": 16.0,
            "ttl_seconds": 6 * 60 * 60,
            "created_at": created_at,
            "ttl_expires_at": created_at + timedelta(hours=6),
            "user_attributed_at": self.now - timedelta(hours=2),
            "ended_at": self.now - timedelta(hours=1),
            "ended_reason": SandboxSession.EndedReason.CLEANUP,
        }
        defaults.update(overrides)
        return SandboxSession.objects.unscoped().create(**defaults)

    def _reload(self, session: SandboxSession) -> SandboxSession:
        return SandboxSession.objects.unscoped().get(id=session.id)

    @parameterized.expand([(False, SettlementOutcome.SETTLED), (True, SettlementOutcome.DUPLICATE)])
    def test_success_stores_the_gateway_amount_and_entry(self, duplicate: bool, expected: SettlementOutcome) -> None:
        session = self._session()
        with patch(HTTPX_POST, return_value=_ok(duplicate=duplicate)) as post:
            assert settle_sandbox_session(session) == expected

        assert post.call_args.args[0] == f"{GATEWAY_URL}/internal/teams/{self.team.id}/reported-spend"
        assert post.call_args.kwargs["headers"]["X-Internal-Actor"] == "tasks-compute"
        settled = self._reload(session)
        assert settled.compute_settled_at is not None
        assert settled.compute_settled_usd == Decimal("1.500000")
        assert settled.compute_ledger_entry_id == "entry-1"

    def test_body_shape_is_clamped_and_byte_identical_across_retries(self) -> None:
        session = self._session(
            with_actor=False,
            created_at=self.now - timedelta(hours=7),
            user_attributed_at=self.now - timedelta(hours=6, minutes=30),
            ttl_expires_at=self.now - timedelta(hours=6),
            ended_at=self.now - timedelta(hours=1),
        )
        with patch(HTTPX_POST, side_effect=[httpx.ConnectError("refused"), _response(503)]) as post:
            settle_sandbox_session(session)
            Task.objects.filter(runs__id=session.task_run_id).update(created_by=self.user)
            settle_sandbox_session(self._reload(session))

        first, second = (json.dumps(call.kwargs["json"]) for call in post.call_args_list)
        assert first == second
        body = post.call_args_list[0].kwargs["json"]
        assert "user" not in body
        assert body["reference"] == f"compute:{session.id}"
        assert body["obo"] == str(self.team.id)
        assert body["run"] == str(session.task_run_id)
        assert body["billable"] is True
        assert body["charge_kind"] == "compute"
        assert body["product"] == "posthog_code"
        assert body["amount_usd"] == "0.770400"
        detail = body["detail"]
        assert detail["window_end"] == session.ttl_expires_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        assert detail["attributed_seconds"] == 1800.0
        assert detail["resource"] == "modal"
        assert [card["version"] for card in detail["rate_cards"]] == ["v1"]
        assert detail["rate_cards"][0]["usd"] == "0.770400"
        assert len(json.dumps(detail).encode()) <= 2048

    def test_body_pins_the_acting_user(self) -> None:
        session = self._session()
        with patch(HTTPX_POST, return_value=_ok()) as post:
            settle_sandbox_session(session)

        assert post.call_args.kwargs["json"]["user"] == self.user.distinct_id

    @parameterized.expand(
        [
            ("conflict", _response(409, {"error": "reference reused"}), SettlementOutcome.CONFLICT, [], "http_409"),
            ("unexpected", _response(418), SettlementOutcome.CONFLICT, [], "unexpected_status"),
            (
                "validation",
                _response(400, {"error": "bad"}),
                SettlementOutcome.CONTRACT_ERROR,
                [SettlementOutcome.CONTRACT_ERROR_REPEAT],
                "",
            ),
            (
                "validation_request_id",
                [
                    _response(400, {"code": "bad_request", "message": "pool_type must be prepaid", "request_id": "a1"}),
                    _response(400, {"code": "bad_request", "message": "pool_type must be prepaid", "request_id": "b2"}),
                ],
                SettlementOutcome.CONTRACT_ERROR,
                [SettlementOutcome.CONTRACT_ERROR_REPEAT],
                "",
            ),
            ("unavailable", _response(503), SettlementOutcome.RETRY, [SettlementOutcome.RETRY], ""),
            ("timeout", _response(408), SettlementOutcome.RETRY, [SettlementOutcome.RETRY], ""),
            ("rate_limited", _response(429), SettlementOutcome.RETRY, [SettlementOutcome.RETRY], ""),
            ("transport", httpx.ConnectError("refused"), SettlementOutcome.RETRY, [SettlementOutcome.RETRY], ""),
        ]
    )
    def test_failure_statuses(
        self,
        _name: str,
        result: Any,
        expected: SettlementOutcome,
        again: list[SettlementOutcome],
        park_reason: str,
    ) -> None:
        session = self._session()
        mock = MagicMock(side_effect=result) if isinstance(result, Exception | list) else MagicMock(return_value=result)
        with patch(HTTPX_POST, mock):
            assert settle_sandbox_session(session) == expected
            assert settle_task_run_compute(session.task_run_id, self.team.id) == again

        row = self._reload(session)
        assert row.compute_settled_at is None
        assert (row.compute_settle_conflict_at is not None) is bool(park_reason)
        assert row.compute_settle_park_reason == park_reason
        assert row.compute_settle_attempts == 0
        assert row.compute_settle_attempted_at is not None
        assert mock.call_count == 1 + len(again)
        transient = expected == SettlementOutcome.RETRY
        first = result[0] if isinstance(result, list) else result
        assert row.compute_settle_error.startswith("" if transient else f"HTTP {first.status_code}: ")
        assert (row.compute_settle_error == "") is transient
        if isinstance(result, list):
            assert row.compute_settle_error == "HTTP 400: bad_request: pool_type must be prepaid"

    def test_retry_cap_excludes_the_row(self) -> None:
        session = self._session()
        with patch(HTTPX_POST, return_value=_response(200, {"duplicate": False})):
            outcomes = [settle_sandbox_session(self._reload(session)) for _ in range(20)]

        assert outcomes == [SettlementOutcome.RETRY] * 19 + [SettlementOutcome.ATTEMPTS_EXHAUSTED]
        row = self._reload(session)
        assert row.compute_settle_error == "attempts_exhausted"
        assert row.compute_settle_park_reason == "attempts_exhausted"
        assert row.compute_settle_conflict_at is not None
        assert row.compute_settled_at is None

    def test_unpark_clears_only_the_requested_reason_in_the_window(self) -> None:
        parked_at = self.now - timedelta(hours=1)
        frozen_body = {"reference": "compute:frozen", "amount_usd": "1.000000"}
        rejected = self._session(
            compute_settle_conflict_at=parked_at,
            compute_settle_park_reason="http_400",
            compute_settle_error="HTTP 400: bad",
            compute_settle_attempts=3,
            compute_settle_body=frozen_body,
            compute_settle_attempted_at=parked_at,
        )
        exhausted = self._session(
            compute_settle_conflict_at=parked_at,
            compute_settle_park_reason="attempts_exhausted",
            compute_settle_error="attempts_exhausted",
            compute_settle_attempts=20,
            compute_settle_body=frozen_body,
            compute_settle_attempted_at=parked_at,
        )
        reused = self._session(
            compute_settle_conflict_at=parked_at,
            compute_settle_park_reason="http_409",
            compute_settle_error="HTTP 409: reused",
        )
        older = self._session(
            compute_settle_conflict_at=self.now - timedelta(days=3),
            compute_settle_park_reason="http_400",
            compute_settle_error="HTTP 400: bad",
        )

        assert unpark_sandbox_compute("http_400", self.now - timedelta(days=1), self.now) == 1

        row = self._reload(rejected)
        assert row.compute_settle_conflict_at is None
        assert row.compute_settle_park_reason == ""
        assert row.compute_settle_error == ""
        assert row.compute_settle_attempts == 0
        assert row.compute_settle_body == {}
        assert row.compute_settle_attempted_at is None
        assert self._reload(reused).compute_settle_park_reason == "http_409"
        assert self._reload(older).compute_settle_conflict_at is not None
        assert self._reload(exhausted).compute_settle_park_reason == "attempts_exhausted"

        assert unpark_sandbox_compute("attempts_exhausted", self.now - timedelta(days=1), self.now) == 1

        row = self._reload(exhausted)
        assert row.compute_settle_conflict_at is None
        assert row.compute_settle_attempts == 0
        assert row.compute_settle_body == frozen_body
        assert row.compute_settle_attempted_at is None

    def test_deployment_error_raises_and_leaves_the_row_untouched(self) -> None:
        session = self._session()
        with patch(HTTPX_POST, return_value=_response(403)), pytest.raises(ComputeSettlementDeploymentError):
            settle_sandbox_session(session)

        row = self._reload(session)
        assert row.compute_settled_at is None
        assert row.compute_settle_conflict_at is None
        assert row.compute_settle_attempts == 0
        assert row.compute_settle_error == ""

    def test_flag_off_is_a_no_op(self) -> None:
        session = self._session()
        with override_settings(GATEWAY_COMPUTE_DEBIT_ENABLED=False), patch(HTTPX_POST) as post:
            assert settle_sandbox_session(session) == SettlementOutcome.DISABLED
            assert settle_task_run_compute(session.task_run_id, self.team.id) == []
            assert settle_overdue_sandbox_compute(self.now) == []

        post.assert_not_called()
        assert self._reload(session).compute_settled_at is None

    @parameterized.expand([("unattributed", True), ("zero_amount", False)])
    def test_settles_locally_without_a_call(self, _name: str, unattributed: bool) -> None:
        ended_at = self.now - timedelta(hours=1)
        session = self._session(user_attributed_at=None if unattributed else ended_at, ended_at=ended_at)
        with patch(HTTPX_POST) as post:
            assert settle_sandbox_session(session) == SettlementOutcome.SETTLED_LOCALLY

        post.assert_not_called()
        row = self._reload(session)
        assert row.compute_settled_at is not None
        assert row.compute_settled_usd == Decimal(0)

    def test_sweep_selects_overdue_rows_only(self) -> None:
        straggler = self._session(ended_at=self.now - timedelta(minutes=30))
        fresh = self._session(ended_at=self.now - timedelta(minutes=2))
        expired_open = self._session(
            ended_at=None,
            ended_reason=None,
            created_at=self.now - timedelta(hours=8),
            user_attributed_at=self.now - timedelta(hours=7, minutes=30),
        )
        hogland_open = self._session(
            ended_at=None,
            ended_reason=None,
            sandbox_backend="hogland",
            created_at=self.now - timedelta(hours=8),
            user_attributed_at=self.now - timedelta(hours=7, minutes=30),
        )

        with patch(HTTPX_POST, return_value=_ok()) as post:
            outcomes = settle_overdue_sandbox_compute(self.now)
            again = settle_overdue_sandbox_compute(self.now)

        assert outcomes == [SettlementOutcome.SETTLED, SettlementOutcome.SETTLED]
        assert again == []
        assert post.call_count == 2
        assert self._reload(straggler).compute_settled_at is not None
        assert self._reload(fresh).compute_settled_at is None
        closed = self._reload(expired_open)
        assert closed.ended_reason == SandboxSession.EndedReason.TTL_SWEEP
        assert closed.compute_settled_at is not None
        untouched = self._reload(hogland_open)
        assert untouched.ended_at is None
        assert untouched.compute_settled_at is None

    @parameterized.expand(
        [("settles", _ok(), SettlementOutcome.SETTLED), ("retries", _response(503), SettlementOutcome.RETRY)]
    )
    def test_sweep_drains_every_batch_once(
        self, _name: str, response: httpx.Response, expected: SettlementOutcome
    ) -> None:
        sessions = [self._session(ended_at=self.now - timedelta(minutes=20 + index)) for index in range(5)]
        with patch(HTTPX_POST, return_value=response) as post:
            assert settle_overdue_sandbox_compute(self.now, batch_size=2) == [expected] * 5

        assert post.call_count == 5
        for session in sessions:
            row = self._reload(session)
            assert (row.compute_settled_at is not None) is (expected == SettlementOutcome.SETTLED)
            assert row.compute_settle_attempts == 0

    def test_sweep_rotates_past_rows_it_already_retried(self) -> None:
        oldest = self._session(ended_at=self.now - timedelta(minutes=40))
        newer = self._session(ended_at=self.now - timedelta(minutes=30))
        with patch(HTTPX_POST, return_value=_response(503)) as post:
            first = settle_overdue_sandbox_compute(self.now, batch_size=1, time_budget=timedelta(0))
            assert [call.kwargs["json"]["reference"] for call in post.call_args_list] == [f"compute:{oldest.id}"]
            assert self._reload(oldest).compute_settle_attempted_at is not None
            post.reset_mock()
            second = settle_overdue_sandbox_compute(self.now, batch_size=1, time_budget=timedelta(0))
            assert [call.kwargs["json"]["reference"] for call in post.call_args_list] == [f"compute:{newer.id}"]

        assert first == [SettlementOutcome.RETRY]
        assert second == [SettlementOutcome.RETRY]

    def test_sweep_stops_on_a_deployment_error(self) -> None:
        self._session(ended_at=self.now - timedelta(minutes=30))
        self._session(ended_at=self.now - timedelta(minutes=40))
        with patch(HTTPX_POST, return_value=_response(401)) as post:
            assert settle_overdue_sandbox_compute(self.now) == []

        assert post.call_count == 1

    @parameterized.expand(
        [
            ("lone_repeat_parks", False, False, [SettlementOutcome.CONFLICT]),
            (
                "repeat_parks_beside_a_settled_row",
                True,
                True,
                [SettlementOutcome.CONTRACT_ERROR, SettlementOutcome.SETTLED, SettlementOutcome.CONFLICT],
            ),
            (
                "shared_error_without_success_stops",
                False,
                True,
                [SettlementOutcome.CONTRACT_ERROR, SettlementOutcome.CONTRACT_ERROR_REPEAT],
            ),
        ]
    )
    def test_sweep_parks_repeated_contract_errors(
        self, _name: str, with_success: bool, with_fresh_failure: bool, expected: list[SettlementOutcome]
    ) -> None:
        repeat = self._session(ended_at=self.now - timedelta(minutes=40))
        fresh = self._session(ended_at=self.now - timedelta(minutes=30)) if with_fresh_failure else None
        success = self._session(ended_at=self.now - timedelta(minutes=20)) if with_success else None
        with patch(HTTPX_POST, return_value=_response(400, {"error": "bad"})):
            assert settle_sandbox_session(repeat) == SettlementOutcome.CONTRACT_ERROR
        stored = self._reload(repeat).compute_settle_error
        assert stored.startswith("HTTP 400: ")

        def respond(_url: str, **kwargs: Any) -> httpx.Response:
            if success is not None and kwargs["json"]["reference"] == f"compute:{success.id}":
                return _ok()
            return _response(400, {"error": "bad"})

        with (
            patch(HTTPX_POST, side_effect=respond),
            patch("products.tasks.backend.logic.services.compute_settlement.logger") as logger,
        ):
            assert settle_overdue_sandbox_compute(self.now) == expected

        parks = SettlementOutcome.CONFLICT in expected
        stopped = [
            call for call in logger.exception.call_args_list if call.args[0] == "compute_settlement.sweep_stopped"
        ]
        assert bool(stopped) is not parks
        row = self._reload(repeat)
        assert row.compute_settle_error == stored
        assert (row.compute_settle_conflict_at is not None) is parks
        assert row.compute_settle_park_reason == ("http_400" if parks else "")
        if fresh is not None:
            fresh_row = self._reload(fresh)
            assert fresh_row.compute_settle_conflict_at is None
            assert fresh_row.compute_settle_error == stored
        if success is not None:
            assert self._reload(success).compute_settled_at is not None

    def test_reconciliation_compares_per_customer_team(self) -> None:
        since = self.now - timedelta(days=1)
        self._session(
            compute_settled_at=self.now - timedelta(minutes=5),
            compute_settled_usd=Decimal("1.540800"),
            compute_ledger_entry_id="entry-1",
        )
        self._session(
            created_at=since - timedelta(hours=2),
            user_attributed_at=since - timedelta(hours=1),
            ended_at=since + timedelta(hours=1),
            compute_settled_at=self.now - timedelta(minutes=5),
            compute_settled_usd=Decimal("3.081600"),
            compute_ledger_entry_id="entry-2",
        )
        rows = [
            {"keys": {"obo": str(self.team.id)}, "compute_usd": "4.622400", "billable_compute_usd": "4.622400"},
            {"keys": {"obo": "999"}, "compute_usd": "2.000000", "billable_compute_usd": "0"},
        ]
        report = httpx.Response(200, json={"rows": rows}, request=httpx.Request("GET", GATEWAY_URL))
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=report) as get:
            result = reconcile_compute_settlement(since, self.now, self.team.id)

        assert get.call_args.kwargs["params"]["group_by"] == "obo,charge_kind"
        assert result.writer_parity == (
            TeamComputeDelta(
                team_id=str(self.team.id), local_usd=Decimal("4.622400"), gateway_usd=Decimal("4.622400"), local_rows=2
            ),
            TeamComputeDelta(team_id="999", local_usd=Decimal(0), gateway_usd=Decimal("2.000000"), local_rows=0),
        )
        assert result.pricing_parity[0].local_usd == Decimal("4.622400")
        billing = result.billing_parity[0]
        assert billing.team_id == str(self.team.id)
        assert billing.local_rows == 2
        assert abs(billing.delta_usd) <= CENT_ROUNDING_TOLERANCE_USD
