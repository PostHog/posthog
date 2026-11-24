import hashlib
from datetime import timedelta
from typing import Any

from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone as django_timezone

import requests
from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import FencedRunTokensRow
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.run_token_fencing import REVOKE_PENDING_STATE_KEY, TOKEN_HASHES_STATE_KEY
from products.tasks.backend.task_profiles import USER
from products.tasks.backend.temporal.process_task.ai_gateway_token import mint_scoped_token

GATEWAY_POST = "products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post"
FLAG_PAYLOAD = "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload"
TOKEN_HASH = "a" * 64


def _answer(status_code: int, body: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body or {}
    response.text = ""
    return response


@override_settings(
    SANDBOX_AI_GATEWAY_URL="https://gateway.example.com",
    SANDBOX_AI_GATEWAY_MINT_KEY="phs_test_mint",
    SANDBOX_AI_GATEWAY_TOKEN_CAP_USD="3",
    SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS=14400,
    SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES="",
    SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES="",
)
class TestRunTokenFencing(TestCase):
    def setUp(self) -> None:
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")

    def _run(
        self,
        *,
        status: str = TaskRun.Status.COMPLETED,
        environment: str = TaskRun.Environment.CLOUD,
        ended_ago: timedelta = timedelta(minutes=5),
        token_hashes: tuple[str, ...] = (TOKEN_HASH,),
        revoke_pending: bool = False,
    ) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            profile=USER.key,
        )
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=status,
            environment=environment,
            state={
                **({TOKEN_HASHES_STATE_KEY: list(token_hashes)} if token_hashes else {}),
                **({REVOKE_PENDING_STATE_KEY: True} if revoke_pending else {}),
            },
        )
        ended_at = django_timezone.now() - ended_ago
        TaskRun.objects.filter(id=run.id).update(
            updated_at=ended_at,
            completed_at=ended_at if status not in (TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS) else None,
        )
        return run

    def test_minting_for_a_run_records_the_token_hash_on_it(self) -> None:
        run = self._run(status=TaskRun.Status.IN_PROGRESS, token_hashes=())

        with patch(GATEWAY_POST, return_value=_answer(201, {"token": "phe_abc"})):
            token = mint_scoped_token(ai_product="signals_scout", team_id=self.team.id, run_id=str(run.id))

        run.refresh_from_db()
        assert token == "phe_abc"
        assert run.state[TOKEN_HASHES_STATE_KEY] == [hashlib.sha256(b"phe_abc").hexdigest()]

    def test_a_token_that_cannot_be_recorded_is_revoked_and_not_returned(self) -> None:
        run = self._run(status=TaskRun.Status.IN_PROGRESS, token_hashes=())

        with (
            patch(
                GATEWAY_POST, side_effect=[_answer(201, {"token": "phe_abc"}), _answer(200, {"revoked": True})]
            ) as post,
            patch(
                "products.tasks.backend.run_token_fencing.TaskRun.mutate_state_atomic",
                side_effect=OperationalError("connection lost"),
            ),
        ):
            token = mint_scoped_token(ai_product="signals_scout", team_id=self.team.id, run_id=str(run.id))

        assert token is None
        assert post.call_args.kwargs["json"] == {"token": "phe_abc"}

    @parameterized.expand(
        [
            ("that_no_longer_exists", "00000000-0000-4000-8000-000000000000"),
            ("with_a_malformed_id", "not-a-run-id"),
        ]
    )
    def test_a_token_minted_for_an_unknown_run_is_revoked_and_not_returned(self, _name: str, run_id: str) -> None:
        with patch(
            GATEWAY_POST, side_effect=[_answer(201, {"token": "phe_abc"}), _answer(200, {"revoked": True})]
        ) as post:
            token = mint_scoped_token(ai_product="signals_scout", team_id=self.team.id, run_id=run_id)

        assert token is None
        assert post.call_args.kwargs["json"] == {"token": "phe_abc"}

    def test_a_run_with_more_hashes_than_one_request_takes_is_revoked_in_full(self) -> None:
        stored = tuple(f"{number:064d}" for number in range(150))
        run = self._run(token_hashes=stored)

        with (
            patch(FLAG_PAYLOAD, return_value={USER.key: "enforce"}),
            patch(GATEWAY_POST, return_value=_answer(200, {"revoked": True})) as post,
        ):
            rows = tasks_facade.fence_ended_task_runs()

        run.refresh_from_db()
        sent = [call.kwargs["json"]["token_hashes"] for call in post.call_args_list]
        assert [len(hashes) for hashes in sent] == [100, 50]
        assert sorted(token_hash for hashes in sent for token_hash in hashes) == sorted(stored)
        assert TOKEN_HASHES_STATE_KEY not in run.state
        assert rows == [FencedRunTokensRow(profile=USER.key, outcome="revoked", count=150)]

    @parameterized.expand(
        [
            ("completed_run", "enforce", {}, "revoked"),
            ("failed_run", "enforce", {"status": TaskRun.Status.FAILED}, "revoked"),
            ("cancelled_run", "enforce", {"status": TaskRun.Status.CANCELLED}, "revoked"),
            ("shadow_mode", "shadow", {}, "would_revoke"),
            ("mode_off", "off", {}, None),
            ("live_run", "enforce", {"status": TaskRun.Status.IN_PROGRESS}, None),
            ("resumed_run_back_in_the_queue", "enforce", {"status": TaskRun.Status.QUEUED}, None),
            ("local_run", "enforce", {"environment": TaskRun.Environment.LOCAL}, None),
            ("run_that_ended_over_an_hour_ago", "enforce", {"ended_ago": timedelta(hours=2)}, None),
            (
                "older_run_whose_revoke_failed_before",
                "enforce",
                {"ended_ago": timedelta(hours=2), "revoke_pending": True},
                "revoked",
            ),
            (
                "failed_revoke_older_than_any_token",
                "enforce",
                {"ended_ago": timedelta(hours=25), "revoke_pending": True},
                None,
            ),
        ]
    )
    def test_fencing_revokes_only_tokens_of_recently_ended_cloud_runs(
        self, _name: str, mode: str, run_overrides: dict[str, Any], outcome: str | None
    ) -> None:
        run = self._run(**run_overrides)

        with (
            patch(FLAG_PAYLOAD, return_value={USER.key: mode}),
            patch(GATEWAY_POST, return_value=_answer(200, {"revoked": True})) as post,
        ):
            rows = tasks_facade.fence_ended_task_runs()

        run.refresh_from_db()
        revoked = outcome == "revoked"
        assert rows == ([FencedRunTokensRow(profile=USER.key, outcome=outcome, count=1)] if outcome else [])
        assert (TOKEN_HASHES_STATE_KEY in run.state) is not revoked
        assert not (revoked and REVOKE_PENDING_STATE_KEY in run.state)
        assert [call.kwargs["json"] for call in post.call_args_list] == (
            [{"token_hashes": [TOKEN_HASH]}] if revoked else []
        )

    @parameterized.expand(
        [
            ("a_number", 5, []),
            ("a_string", TOKEN_HASH, []),
            ("entries_that_are_not_hashes", ["not-a-hash", 7, None], []),
            ("one_real_hash_among_junk", ["not-a-hash", "b" * 64], ["b" * 64]),
        ]
    )
    def test_fencing_only_trusts_stored_hashes_that_look_like_hashes(
        self, _name: str, stored: Any, sent_for_that_run: list[str]
    ) -> None:
        tampered = self._run()
        TaskRun.objects.filter(id=tampered.id).update(state={TOKEN_HASHES_STATE_KEY: stored})
        self._run()

        with (
            patch(FLAG_PAYLOAD, return_value={USER.key: "enforce"}),
            patch(GATEWAY_POST, return_value=_answer(200, {"revoked": True})) as post,
        ):
            tasks_facade.fence_ended_task_runs()

        sent = [token_hash for call in post.call_args_list for token_hash in call.kwargs["json"]["token_hashes"]]
        assert sorted(sent) == sorted([*sent_for_that_run, TOKEN_HASH])

    @parameterized.expand(
        [
            ("that_the_gateway_refused", {"return_value": _answer(503)}),
            ("that_never_reached_the_gateway", {"side_effect": requests.ConnectionError("connection refused")}),
        ]
    )
    def test_a_failed_revoke_keeps_the_hashes_for_the_next_pass(self, _name: str, gateway: dict[str, Any]) -> None:
        run = self._run()

        with (
            patch(FLAG_PAYLOAD, return_value={USER.key: "enforce"}),
            patch(GATEWAY_POST, **gateway),
        ):
            rows = tasks_facade.fence_ended_task_runs()

        run.refresh_from_db()
        assert rows == []
        assert run.state[TOKEN_HASHES_STATE_KEY] == [TOKEN_HASH]
        assert run.state[REVOKE_PENDING_STATE_KEY] is True

    def test_fencing_sends_at_most_a_hundred_hashes_per_request(self) -> None:
        for number in range(3):
            self._run(token_hashes=tuple(f"{number:02d}{position:062d}" for position in range(40)))

        with (
            patch(FLAG_PAYLOAD, return_value={USER.key: "enforce"}),
            patch(GATEWAY_POST, return_value=_answer(200, {"revoked": True})) as post,
        ):
            rows = tasks_facade.fence_ended_task_runs()

        assert sorted(len(call.kwargs["json"]["token_hashes"]) for call in post.call_args_list) == [20, 100]
        assert rows == [FencedRunTokensRow(profile=USER.key, outcome="revoked", count=120)]
