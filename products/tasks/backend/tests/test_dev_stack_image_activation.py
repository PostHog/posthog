import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from unittest.mock import patch

from django.db import connections
from django.utils import timezone

from products.tasks.backend.dev_stack_image_models import DevStackImageAttempt, DevStackImageTarget
from products.tasks.backend.logic.services.dev_stack_image_state import BUILD_BUDGET, DevStackImageState


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
