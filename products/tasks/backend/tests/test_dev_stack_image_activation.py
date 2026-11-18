import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from itertools import combinations
from threading import Barrier

import pytest
from unittest.mock import AsyncMock, Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connections
from django.test import override_settings
from django.utils import timezone

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from products.tasks.backend.dev_stack_image_models import DevStackImageAttempt, DevStackImageTarget
from products.tasks.backend.exceptions import SandboxCleanupError
from products.tasks.backend.logic.services.dev_stack_image_refresh import reconcile_dev_stack_image
from products.tasks.backend.logic.services.dev_stack_image_state import BUILD_BUDGET, DevStackImageState
from products.tasks.backend.logic.services.dev_stack_image_verification import (
    DevStackImageVerificationError,
    verify_dev_stack_image,
)
from products.tasks.backend.logic.services.modal_sandbox import _image_ref_cache, resolve_template_base_image_reference
from products.tasks.backend.logic.services.sandbox import ExecutionResult, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.bake_dev_stack_image.activation import activate_dev_stack_image


@pytest.fixture
def state() -> DevStackImageState:
    target = DevStackImageTarget.objects.create(region="DEV", name="posthog-dev-stack", enabled=True)
    return DevStackImageState(target.pk)


def observe(state: DevStackImageState, base: str = "a", request: str = "") -> None:
    state.observe(state.begin_observation(request), f"sha256:{base}", "b" * 40, "c" * 64)


def claim(state: DevStackImageState) -> tuple[DevStackImageAttempt, uuid.UUID]:
    attempt = state.reconcile()
    assert attempt is not None
    owner = uuid.uuid4()
    claimed = state.claim(attempt.id, owner, "example-run")
    assert claimed is not None
    return claimed, owner


@pytest.mark.django_db
class TestDevStackImageActivation:
    @override_settings(DEBUG=False)
    def test_sweeps_do_not_restore_a_cached_base(self, state: DevStackImageState) -> None:
        token = Mock(status_code=200)
        token.json.return_value = {"token": "example-token"}

        def manifest(digest: str) -> Mock:
            return Mock(status_code=200, headers={"Docker-Content-Digest": f"sha256:{digest * 64}"})

        target = DevStackImageTarget.objects.get(pk=state.target_id)
        try:
            with (
                patch(
                    "products.tasks.backend.logic.services.modal_sandbox.requests.get",
                    side_effect=[
                        token,
                        manifest("a"),
                        TimeoutError(),
                        token,
                        manifest("b"),
                        token,
                        manifest("c"),
                        token,
                        manifest("b"),
                    ],
                ),
                patch("products.tasks.backend.logic.services.modal_sandbox.time.sleep"),
                patch(
                    "products.tasks.backend.logic.services.dev_stack_image_refresh.resolve_repository_sha",
                    return_value="b" * 40,
                ),
                patch(
                    "products.tasks.backend.logic.services.dev_stack_image_refresh.sync_connect",
                    return_value=Mock(
                        start_workflow=AsyncMock(return_value=Mock(first_execution_run_id="example-run"))
                    ),
                ),
            ):
                for index, cached in enumerate(("a", "c")):
                    _image_ref_cache.clear()
                    reference = resolve_template_base_image_reference(SandboxTemplate.VM_BASE)
                    assert reference and reference.endswith(f"sha256:{cached * 64}")
                    assert reconcile_dev_stack_image(target, trigger="base_changed") is (index == 0)
                    if index == 0:
                        claim(state)
            target.refresh_from_db()
            assert target.base_reference.endswith(f"sha256:{'b' * 64}")
            assert target.generation == 1
            assert DevStackImageAttempt.objects.get().status == "building"
        finally:
            _image_ref_cache.clear()

    def test_recipe_deployment_supersedes_pending_bake_without_a_base_change(self, state: DevStackImageState) -> None:
        target = DevStackImageTarget.objects.get(pk=state.target_id)
        with (
            patch(
                "products.tasks.backend.logic.services.modal_sandbox.resolve_template_base_image_reference",
                return_value="ghcr.io/posthog/posthog-sandbox-vm@sha256:" + "a" * 64,
            ),
            patch(
                "products.tasks.backend.logic.services.dev_stack_image_refresh.resolve_repository_sha",
                return_value="b" * 40,
            ),
            patch(
                "products.tasks.backend.logic.services.dev_stack_image_refresh.Path.read_bytes",
                side_effect=[b"recipe one", b"recipe two"],
            ),
            patch(
                "products.tasks.backend.logic.services.dev_stack_image_refresh.sync_connect",
                return_value=Mock(start_workflow=AsyncMock(return_value=Mock(first_execution_run_id="example-run"))),
            ),
        ):
            assert reconcile_dev_stack_image(target, trigger="base_changed")
            previous, owner = claim(state)
            assert reconcile_dev_stack_image(target, trigger="base_changed")
        target.refresh_from_db()
        previous.refresh_from_db()
        assert target.generation == 2
        assert previous.status == "superseded"
        assert not state.renew(previous.id, owner)
        assert target.recipe_sha != previous.recipe_sha
        assert target.attempt_id != previous.id

    def test_initialized_seed_remains_a_verified_rollback_source(self) -> None:
        with patch(
            "products.tasks.backend.management.commands.bake_dev_stack_image.verify_dev_stack_image",
            return_value="1.0.0",
        ):
            call_command("bake_dev_stack_image", initialize=True, seed_image_id="im-seed", stdout=StringIO())
        target = DevStackImageState.target()
        assert target is not None
        seed = target.attempts.get(candidate_image_id="im-seed")
        assert seed.verified_at is not None
        assert (seed.base_reference, seed.repository_sha, seed.recipe_sha) == ("", "", "")
        call_command("bake_dev_stack_image", enable=True, stdout=StringIO())
        state = DevStackImageState(target.pk)
        observe(state)
        first, owner = claim(state)
        assert state.checkpoint(first.id, owner, "im-first")
        assert state.activate(first.id, owner, "im-first", "1.0.1")
        with patch(
            "products.tasks.backend.management.commands.bake_dev_stack_image.reconcile_dev_stack_image",
            return_value=True,
        ):
            call_command("bake_dev_stack_image", rollback_attempt=seed.id, stdout=StringIO())
        rollback, owner = claim(state)
        target.refresh_from_db()
        assert target.active_image_id == "im-first"
        assert not target.auto_refresh
        assert rollback.candidate_image_id == "im-seed"
        assert rollback.status == "verifying"
        assert state.activate(rollback.id, owner, "im-seed", "1.0.0")
        target.refresh_from_db()
        assert target.active_image_id == "im-seed"
        assert target.active_base_reference == ""

    def test_lost_dispatch_acknowledgement_reuses_the_durable_attempt(self, state: DevStackImageState) -> None:
        target = DevStackImageTarget.objects.get(pk=state.target_id)
        client = Mock(
            start_workflow=AsyncMock(side_effect=[TimeoutError(), Mock(first_execution_run_id="example-run")])
        )
        with (
            patch(
                "products.tasks.backend.logic.services.modal_sandbox.resolve_template_base_image_reference",
                return_value="ghcr.io/posthog/posthog-sandbox-vm@sha256:" + "a" * 64,
            ),
            patch(
                "products.tasks.backend.logic.services.dev_stack_image_refresh.resolve_repository_sha",
                return_value="b" * 40,
            ),
            patch("products.tasks.backend.logic.services.dev_stack_image_refresh.sync_connect", return_value=client),
        ):
            with pytest.raises(TimeoutError):
                reconcile_dev_stack_image(target, trigger="base_changed")
            assert reconcile_dev_stack_image(target, trigger="base_changed")
        assert (
            client.start_workflow.call_args_list[0].kwargs["id"] == client.start_workflow.call_args_list[1].kwargs["id"]
        )
        assert DevStackImageAttempt.objects.count() == 1

    def test_rollback_reverifies_known_candidate_and_pauses_automatic_updates(self, state: DevStackImageState) -> None:
        observe(state)
        good, owner = claim(state)
        assert state.checkpoint(good.id, owner, "im-good")
        assert state.activate(good.id, owner, "im-good", "1.0.0")
        observe(state, "next")
        replaced, owner = claim(state)
        assert state.checkpoint(replaced.id, owner, "im-next")
        assert state.activate(replaced.id, owner, "im-next", "1.0.1")
        state.rollback(good.id)
        target = DevStackImageTarget.objects.get(pk=state.target_id)
        assert target.active_image_id == "im-next"
        assert not target.auto_refresh
        observe(state, "current")
        rollback, owner = claim(state)
        assert rollback.candidate_image_id == "im-good"
        assert state.activate(rollback.id, owner, "im-good", "1.0.0")
        target.refresh_from_db()
        assert target.active_generation == 3
        assert target.active_image_id == "im-good"

    def test_late_candidate_cannot_replace_newer_active_image(self, state: DevStackImageState) -> None:
        observe(state)
        older, old_owner = claim(state)
        assert state.checkpoint(older.id, old_owner, "im-old")
        observe(state, "d")
        newer, new_owner = claim(state)
        assert state.checkpoint(newer.id, new_owner, "im-new")
        assert state.activate(newer.id, new_owner, "im-new", "1.0.0")
        assert not state.activate(older.id, old_owner, "im-old", "1.0.0")
        assert not state.renew(older.id, old_owner)
        target = DevStackImageTarget.objects.get(pk=state.target_id)
        assert target.active_image_id == "im-new"
        assert target.active_base_reference == "sha256:d"

    @pytest.mark.parametrize("change", ["generation", "lease", "deadline", "owner", "disabled", "candidate"])
    def test_activation_rechecks_ownership_after_verification(self, state: DevStackImageState, change: str) -> None:
        observe(state)
        attempt, owner = claim(state)
        assert state.checkpoint(attempt.id, owner, "im-candidate")
        if change == "generation":
            observe(state, "d")
        elif change == "lease":
            DevStackImageAttempt.objects.filter(pk=attempt.id).update(lease_expires_at=timezone.now())
        elif change == "deadline":
            DevStackImageAttempt.objects.filter(pk=attempt.id).update(deadline_at=timezone.now())
        elif change == "owner":
            owner = uuid.uuid4()
        elif change == "disabled":
            DevStackImageTarget.objects.filter(pk=state.target_id).update(enabled=False)
        else:
            DevStackImageAttempt.objects.filter(pk=attempt.id).update(candidate_image_id="im-other")
        assert not state.activate(attempt.id, owner, "im-candidate", "1.0.0")
        assert DevStackImageTarget.objects.get(pk=state.target_id).active_image_id == ""

    def test_expired_owner_cannot_activate_after_same_generation_takeover(self, state: DevStackImageState) -> None:
        observe(state)
        old, owner = claim(state)
        assert state.checkpoint(old.id, owner, "im-candidate")
        DevStackImageAttempt.objects.filter(pk=old.id).update(lease_expires_at=timezone.now())
        new, new_owner = claim(state)
        assert new.candidate_image_id == "im-candidate"
        assert not state.activate(old.id, owner, "im-candidate", "1.0.0")
        assert state.checkpoint(new.id, new_owner, "im-candidate")
        assert state.activate(new.id, new_owner, "im-candidate", "1.0.0")

    def test_duplicate_dispatch_and_activation_are_idempotent(self, state: DevStackImageState) -> None:
        observe(state)
        queued = state.reconcile()
        assert queued is not None
        repeated = state.reconcile()
        assert repeated is not None and repeated.id == queued.id
        attempt, owner = claim(state)
        assert state.claim(attempt.id, owner, "example-run") is not None
        assert state.claim(attempt.id, uuid.uuid4(), "duplicate") is None
        assert state.checkpoint(attempt.id, owner, "im-active")
        assert state.activate(attempt.id, owner, "im-active", "1.0.0")
        assert state.activate(attempt.id, owner, "im-active", "1.0.0")
        assert state.reconcile() is None
        assert DevStackImageAttempt.objects.count() == 1

    def test_slow_observation_cannot_restore_old_desired_generation(self, state: DevStackImageState) -> None:
        old_revision = state.begin_observation()
        observe(state, "new")
        assert not state.observe(old_revision, "sha256:old", "b" * 40, "c" * 64)
        assert DevStackImageTarget.objects.get(pk=state.target_id).base_reference == "sha256:new"

    @pytest.mark.parametrize("overlap", [False, True])
    def test_nightly_request_rebuilds_current_base_once(self, state: DevStackImageState, overlap: bool) -> None:
        observe(state)
        attempt, owner = claim(state)
        assert state.checkpoint(attempt.id, owner, "im-current")
        assert state.activate(attempt.id, owner, "im-current", "1.0.0")
        revision = state.begin_observation("nightly:example-day")
        if overlap:
            sweep_revision = state.begin_observation()
            assert not state.observe(revision, "sha256:older", "d" * 40, "c" * 64)
            revision = sweep_revision
        assert state.observe(revision, "sha256:a", "b" * 40, "c" * 64)
        target = DevStackImageTarget.objects.get(pk=state.target_id)
        assert target.generation == 2 and target.active_generation == 1
        assert target.request_key == "nightly:example-day" and target.pending_request_key == ""
        assert target.base_reference == "sha256:a"
        assert state.reconcile() is not None
        observe(state, request="nightly:example-day")
        target.refresh_from_db()
        assert target.generation == 2

    def test_retry_budget_survives_target_changes(self, state: DevStackImageState) -> None:
        for index in range(BUILD_BUDGET):
            observe(state, str(index))
            attempt, owner = claim(state)
            state.fail(attempt.id, owner)
            assert state.reconcile() is None
        observe(state, "next")
        assert state.reconcile() is None
        target = DevStackImageTarget.objects.get(pk=state.target_id)
        assert target.blocked_reason == "Bake budget exhausted"
        assert target.next_retry_at is not None
        with patch(
            "products.tasks.backend.logic.services.dev_stack_image_state.timezone.now",
            return_value=target.next_retry_at + timedelta(seconds=1),
        ):
            assert state.reconcile() is not None

    def test_invalid_candidate_preserves_last_good_image_and_blocks_retries(self, state: DevStackImageState) -> None:
        observe(state)
        old, owner = claim(state)
        assert state.checkpoint(old.id, owner, "im-good")
        assert state.activate(old.id, owner, "im-good", "1.0.0")
        observe(state, "next")
        failed, owner = claim(state)
        state.fail(failed.id, owner, invalid=True)
        assert state.reconcile() is None
        target = DevStackImageTarget.objects.get(pk=state.target_id)
        assert target.active_image_id == "im-good"
        assert target.blocked_reason == "Candidate verification failed"


@pytest.mark.parametrize(
    "failure,cleanup_failures",
    [(failure, 0) for failure in (None, "seed", "boot", "manifest", "agent", "health", "checkout", "invalid_json")]
    + [(None, 1), (None, 3), ("health", 3)],
)
def test_candidate_must_boot_and_match_manifest_before_activation(
    failure: str | None, cleanup_failures: int, caplog: pytest.LogCaptureFixture
) -> None:
    attempt = DevStackImageAttempt(base_reference="sha256:example", repository_sha="a" * 40, recipe_sha="b" * 64)
    manifest = {
        "base_reference": attempt.base_reference,
        "posthog_sha": attempt.repository_sha,
        "recipe_sha": attempt.recipe_sha,
        "agent_version": "1.0.0",
    }
    if failure == "manifest":
        manifest["base_reference"] = "sha256:other"
    if failure == "seed":
        attempt.base_reference = attempt.repository_sha = attempt.recipe_sha = ""
    sandbox = Mock(id="sb-verification")
    sandbox.destroy.side_effect = [
        SandboxCleanupError("cleanup failed", {}, RuntimeError("provider cleanup failed"), capture=False)
    ] * cleanup_failures + [None]
    output = "x" * 5_000 + "diagnostic tail"
    sandbox.execute.side_effect = [
        ExecutionResult(
            stdout="invalid" if failure == "invalid_json" else json.dumps(manifest), stderr="", exit_code=0
        ),
        ExecutionResult(stdout="0.9.0" if failure == "agent" else "1.0.0", stderr="", exit_code=0),
        ExecutionResult(stdout=output, stderr=output, exit_code=1 if failure == "checkout" else 0),
        ExecutionResult(stdout=output, stderr=output, exit_code=1 if failure == "health" else 0),
    ]

    def create(config: SandboxConfig) -> Mock:
        assert config.base_image_reference == (attempt.base_reference or None)
        assert config.snapshot_external_id == "im-candidate"
        assert config.require_snapshot
        config.snapshot_restored = failure != "boot"
        return sandbox

    with (
        patch(
            "products.tasks.backend.logic.services.dev_stack_image_verification.get_sandbox_class",
            return_value=Mock(create=create),
        ),
        patch("products.tasks.backend.logic.services.dev_stack_image_verification.time.sleep"),
    ):
        if failure not in (None, "seed"):
            with pytest.raises(RuntimeError if failure in ("boot", "checkout") else DevStackImageVerificationError):
                verify_dev_stack_image(attempt, "im-candidate")
        else:
            assert verify_dev_stack_image(attempt, "im-candidate") == "1.0.0"
    assert sandbox.destroy.call_count == min(cleanup_failures + 1, 3)
    if failure in ("checkout", "health"):
        record = next(
            record for record in caplog.records if record.message == "dev_stack_image_verification_command_failed"
        )
        assert (
            record.__dict__.items()
            >= {
                "stage": "checkout" if failure == "checkout" else "datastores",
                "exit_code": 1,
                "attempt_id": str(attempt.id),
                "image_id": "im-candidate",
                "sandbox_id": sandbox.id,
                "stdout_tail": output[-4_000:],
                "stderr_tail": output[-4_000:],
            }.items()
        )
    if cleanup_failures == 3:
        record = next(
            record for record in caplog.records if record.message == "dev_stack_image_verification_cleanup_failed"
        )
        assert record.__dict__["sandbox_id"] == sandbox.id


@pytest.mark.parametrize("actions", list(combinations(("initialize", "enable", "disable", "rollback_attempt"), 2)))
def test_conflicting_lifecycle_actions_do_not_change_state(actions: tuple[str, str]) -> None:
    options = {key: uuid.uuid4() if key == "rollback_attempt" else True for key in actions}
    args = [
        f"--{key.replace('_', '-')}{'=' + str(value) if key == 'rollback_attempt' else ''}"
        for key, value in options.items()
    ]
    with pytest.raises(CommandError, match="not allowed with argument"):
        call_command("bake_dev_stack_image", *args)
    with pytest.raises(CommandError, match="Choose only one"):
        call_command("bake_dev_stack_image", **options)


@pytest.mark.django_db(transaction=True)
def test_concurrent_sweeps_reserve_one_attempt(state: DevStackImageState) -> None:
    observe(state)
    barrier = Barrier(2, timeout=10)

    def reconcile() -> uuid.UUID:
        try:
            barrier.wait()
            attempt = state.reconcile()
            assert attempt is not None
            return attempt.id
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reconcile) for _ in range(2)]
        assert futures[0].result(timeout=10) == futures[1].result(timeout=10)
    assert DevStackImageAttempt.objects.count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "invalid", "provider", "connection"])
async def test_activation_activity_preserves_active_image_until_verification(failure: str | None) -> None:
    target = await DevStackImageTarget.objects.acreate(
        region="DEV",
        name="posthog-dev-stack",
        enabled=True,
        generation=1,
        base_reference="sha256:example",
        repository_sha="a" * 40,
        recipe_sha="b" * 64,
        active_image_id="im-existing",
    )
    state = DevStackImageState(target.pk)
    attempt = await sync_to_async(state.reconcile)()
    assert attempt is not None
    error = (
        DevStackImageVerificationError("invalid")
        if failure == "invalid"
        else RuntimeError("provider unavailable")
        if failure == "provider"
        else None
    )
    original_checkpoint = DevStackImageState.checkpoint
    checkpoint_calls = 0

    def checkpoint(state: DevStackImageState, attempt_id: uuid.UUID, owner: uuid.UUID, image_id: str) -> bool:
        nonlocal checkpoint_calls
        checkpoint_calls += 1
        if failure == "connection" and checkpoint_calls == 1:
            raise OperationalError("connection closed")
        return original_checkpoint(state, attempt_id, owner, image_id)

    with (
        patch.object(DevStackImageState, "checkpoint", checkpoint),
        patch(
            "products.tasks.backend.temporal.bake_dev_stack_image.activation.bake_dev_stack_image",
            return_value="im-candidate",
        ),
        patch(
            "products.tasks.backend.temporal.bake_dev_stack_image.activation.verify_dev_stack_image",
            return_value="1.0.0",
            side_effect=error,
        ),
    ):
        if error:
            with pytest.raises(type(error)):
                await ActivityEnvironment().run(activate_dev_stack_image, str(attempt.id))
        else:
            assert await ActivityEnvironment().run(activate_dev_stack_image, str(attempt.id)) == "im-candidate"
    await target.arefresh_from_db()
    assert target.active_image_id == ("im-existing" if error else "im-candidate")
    if failure == "provider":
        assert target.blocked_reason == ""
        assert target.next_retry_at is not None
        with patch(
            "products.tasks.backend.logic.services.dev_stack_image_state.timezone.now",
            return_value=target.next_retry_at,
        ):
            retry = await sync_to_async(state.reconcile)()
        assert retry is not None and retry.candidate_image_id == "im-candidate"
    if failure == "connection":
        assert checkpoint_calls == 2
