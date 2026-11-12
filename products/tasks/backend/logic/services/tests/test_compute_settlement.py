import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

import httpx
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import hash_key_value

from products.tasks.backend.logic.services.compute_settlement import (
    ComputeReconciliation,
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
        assert body["strict"] is True
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
                "insufficient_credits",
                _response(
                    402,
                    {
                        "code": "insufficient_credits",
                        "message": "reported spend refused: team wallet has insufficient funds",
                    },
                ),
                SettlementOutcome.INSUFFICIENT_CREDITS,
                [],
                "http_402",
            ),
            (
                "payment_required_other_code",
                _response(402, {"code": "cap_exceeded", "message": "team hard spend cap exceeded"}),
                SettlementOutcome.CONFLICT,
                [],
                "unexpected_status",
            ),
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
        refused = self._session(
            compute_settle_conflict_at=parked_at,
            compute_settle_park_reason="http_402",
            compute_settle_error="HTTP 402: insufficient_credits",
            compute_settle_attempts=1,
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
        assert self._reload(refused).compute_settle_park_reason == "http_402"

        assert unpark_sandbox_compute("attempts_exhausted", self.now - timedelta(days=1), self.now) == 1

        row = self._reload(exhausted)
        assert row.compute_settle_conflict_at is None
        assert row.compute_settle_attempts == 0
        assert row.compute_settle_body == frozen_body
        assert row.compute_settle_attempted_at is None

        assert unpark_sandbox_compute("http_402", self.now - timedelta(days=1), self.now) == 1

        row = self._reload(refused)
        assert row.compute_settle_conflict_at is None
        assert row.compute_settle_park_reason == ""
        assert row.compute_settle_error == ""
        assert row.compute_settle_attempts == 0
        assert row.compute_settle_body == frozen_body
        assert row.compute_settle_attempted_at is None
        assert self._reload(reused).compute_settle_park_reason == "http_409"

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

    def test_settle_since_leaves_earlier_rows_alone(self) -> None:
        before = self._session(user_attributed_at=self.now - timedelta(hours=4), ended_at=self.now - timedelta(hours=3))
        after = self._session(ended_at=self.now - timedelta(minutes=30))

        with (
            override_settings(GATEWAY_COMPUTE_SETTLE_SINCE=(self.now - timedelta(hours=1)).isoformat()),
            patch(HTTPX_POST, return_value=_ok()) as post,
            patch("posthog.metrics.push_registry") as push,
        ):
            assert settle_overdue_sandbox_compute(self.now) == [SettlementOutcome.SETTLED]

        assert post.call_count == 1
        body = post.call_args.kwargs["json"]
        assert body["amount_usd"] == "2.311200"
        assert body["detail"]["attributed_seconds"] == 5400.0
        assert self._reload(before).compute_settled_at is None
        assert self._reload(after).compute_settled_at is not None
        registry = push.call_args.args[1]
        assert registry.get_sample_value("posthog_tasks_sandbox_sessions_unsettled_over_hour") == 0

    def test_settle_since_bounds_run_end_settlement(self) -> None:
        before = self._session(user_attributed_at=self.now - timedelta(hours=4), ended_at=self.now - timedelta(hours=3))
        after = self._session(
            task_run=before.task_run,
            user_attributed_at=self.now - timedelta(hours=4),
            ended_at=self.now - timedelta(minutes=30),
        )

        with (
            override_settings(GATEWAY_COMPUTE_SETTLE_SINCE=(self.now - timedelta(hours=1)).isoformat()),
            patch(HTTPX_POST, return_value=_ok()) as post,
        ):
            assert settle_task_run_compute(before.task_run_id, self.team.id) == [SettlementOutcome.SETTLED]

        assert post.call_count == 1
        assert post.call_args.kwargs["json"]["detail"]["attributed_seconds"] == 12600.0
        assert self._reload(before).compute_settled_at is None
        assert self._reload(after).compute_settled_at is not None

    @parameterized.expand(
        [
            ("malformed_settle_since", "GATEWAY_COMPUTE_SETTLE_SINCE", "not-a-date"),
            ("future_settle_since", "GATEWAY_COMPUTE_SETTLE_SINCE", None),
            ("unresolved_wallet", "SANDBOX_AI_GATEWAY_MINT_KEY", "phs_unknown_mint_key"),
        ]
    )
    def test_deployment_error_stops_sweep_and_still_pushes_gauges(
        self, _name: str, setting: str, value: str | None
    ) -> None:
        self._session(ended_at=self.now - timedelta(minutes=90))
        labels = {"outcome": "deployment_error"}
        errors_before = REGISTRY.get_sample_value("posthog_tasks_compute_settlements_total", labels) or 0

        with (
            override_settings(**{setting: value or (self.now + timedelta(days=1)).isoformat()}),
            patch(HTTPX_POST) as post,
            patch("posthog.metrics.push_registry") as push,
        ):
            assert settle_overdue_sandbox_compute(self.now) == []

        post.assert_not_called()
        assert REGISTRY.get_sample_value("posthog_tasks_compute_settlements_total", labels) == errors_before + 1
        registry = push.call_args.args[1]
        assert registry.get_sample_value("posthog_tasks_sandbox_sessions_unsettled_over_hour") is not None
        assert registry.get_sample_value("posthog_tasks_sandbox_sessions_parked", {"reason": "http_409"}) is not None

    @parameterized.expand([("flag_on", True, 1), ("flag_off", False, 0)])
    def test_sweep_pushes_gauges_after_settling(self, _name: str, enabled: bool, expected_unsettled: int) -> None:
        overdue_at = self.now - timedelta(minutes=90)
        self._session(ended_at=overdue_at)
        stuck = self._session(ended_at=overdue_at)
        broke = self._session(ended_at=overdue_at)
        self._session(ended_at=overdue_at, compute_settled_at=overdue_at, compute_settled_usd=Decimal(0))
        self._session(ended_at=overdue_at, compute_settle_conflict_at=overdue_at, compute_settle_park_reason="http_409")
        self._session(ended_at=overdue_at, user_attributed_at=None)
        self._session(ended_at=self.now - timedelta(minutes=30))
        self._session(
            ended_at=None, ended_reason=None, sandbox_backend="hogland", created_at=self.now - timedelta(days=2)
        )
        self._session(
            ended_at=None, ended_reason=None, sandbox_backend="hogland", created_at=self.now - timedelta(hours=20)
        )

        def respond(_url: str, **kwargs: Any) -> httpx.Response:
            if kwargs["json"]["reference"] == f"compute:{stuck.id}":
                return _response(503)
            if kwargs["json"]["reference"] == f"compute:{broke.id}":
                return _response(402, {"code": "insufficient_credits", "message": "team wallet has insufficient funds"})
            return _ok()

        with (
            override_settings(GATEWAY_COMPUTE_DEBIT_ENABLED=enabled),
            patch(HTTPX_POST, side_effect=respond),
            patch("posthog.metrics.push_registry") as push,
        ):
            settle_overdue_sandbox_compute(self.now)

        push.assert_called_once()
        assert push.call_args.args[0] == "tasks_compute_settlement"
        registry = push.call_args.args[1]
        assert registry.get_sample_value("posthog_tasks_hogland_sandbox_sessions_open_over_day") == 1
        assert registry.get_sample_value("posthog_tasks_sandbox_sessions_unsettled_over_hour") == expected_unsettled
        assert registry.get_sample_value("posthog_tasks_sandbox_sessions_parked", {"reason": "http_402"}) == int(
            enabled
        )
        assert registry.get_sample_value("posthog_tasks_sandbox_sessions_parked", {"reason": "http_409"}) == 1
        assert registry.get_sample_value("posthog_tasks_sandbox_sessions_parked", {"reason": "attempts_exhausted"}) == 0

    def test_sweep_settles_when_the_gauge_push_fails(self) -> None:
        session = self._session()
        with (
            override_settings(PROM_PUSHGATEWAY_ADDRESS="http://pushgateway.internal"),
            patch(HTTPX_POST, return_value=_ok()),
            patch("posthog.metrics.push_to_gateway", side_effect=OSError("refused")) as push,
        ):
            assert settle_overdue_sandbox_compute(self.now) == [SettlementOutcome.SETTLED]

        push.assert_called_once()
        assert self._reload(session).compute_settled_at is not None

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
        report = httpx.Response(200, json={"rows": rows, "truncated": False}, request=httpx.Request("GET", GATEWAY_URL))
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=report) as get:
            result = reconcile_compute_settlement(since, self.now, self.team.id)

        assert get.call_args.kwargs["params"]["group_by"] == "obo,charge_kind"
        assert get.call_args.kwargs["params"]["order_by"] == "key"
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

    def test_sections_list_real_drift_only(self) -> None:
        report = ComputeReconciliation(
            writer_parity=(
                TeamComputeDelta(
                    team_id="11", local_usd=Decimal("5.000000"), gateway_usd=Decimal("5.000000"), local_rows=3
                ),
            ),
            pricing_parity=(
                TeamComputeDelta(
                    team_id="12", local_usd=Decimal("10.000000"), gateway_usd=Decimal("10.000112"), local_rows=25175
                ),
                TeamComputeDelta(
                    team_id="13", local_usd=Decimal("20.000000"), gateway_usd=Decimal("17.510000"), local_rows=40
                ),
            ),
            billing_parity=(),
        )
        out = StringIO()

        with patch(
            "products.tasks.backend.management.commands.reconcile_sandbox_compute_settlement."
            "reconcile_compute_settlement",
            return_value=report,
        ):
            call_command("reconcile_sandbox_compute_settlement", wallet_team_id=self.team.id, stdout=out)

        output = out.getvalue()
        totals = [line.split() for line in output.splitlines() if line.strip().startswith("TOTAL")]
        assert totals == [
            ["TOTAL", "5.000000", "5.000000", "0.000000", "3"],
            ["TOTAL", "30.000000", "27.510112", "2.489888", "25215"],
        ]
        assert "10.000112" not in output
        assert "17.510000" in output
        assert "0 of 1 teams listed, 1 within tolerance" in output
        assert "1 of 2 teams listed, 1 within tolerance" in output
        assert "No teams in this window." in output
