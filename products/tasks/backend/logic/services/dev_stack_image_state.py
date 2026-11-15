import uuid
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from posthog.utils import get_instance_region

from products.tasks.backend.constants import DEV_STACK_IMAGE_NAME
from products.tasks.backend.dev_stack_image_models import DevStackImageAttempt, DevStackImageTarget

LEASE_DURATION = timedelta(minutes=2)
BUILD_DEADLINE = timedelta(hours=3)
DISPATCH_DEADLINE = timedelta(minutes=10)
BUDGET_WINDOW = timedelta(hours=6)
BUILD_BUDGET = 3
RETRY_DELAYS = (timedelta(minutes=2), timedelta(minutes=5), timedelta(minutes=15))


class DevStackImageState:
    def __init__(self, target_id: uuid.UUID) -> None:
        self.target_id = target_id

    @staticmethod
    def target(name: str = DEV_STACK_IMAGE_NAME) -> DevStackImageTarget | None:
        return (
            DevStackImageTarget.objects.using("default")
            .filter(region=get_instance_region() or "DEV", name=name)
            .first()
        )

    def begin_observation(self, request_key: str = "") -> int:
        with transaction.atomic():
            target = DevStackImageTarget.objects.using("default").select_for_update().get(pk=self.target_id)
            if request_key and request_key != target.request_key:
                target.pending_request_key = request_key
            target.observation_revision += 1
            target.save(update_fields=["observation_revision", "pending_request_key"])
            return target.observation_revision

    def rollback(self, source_id: uuid.UUID) -> None:
        with transaction.atomic():
            target = DevStackImageTarget.objects.using("default").select_for_update().get(pk=self.target_id)
            source = DevStackImageAttempt.objects.using("default").get(
                pk=source_id, target=target, verified_at__isnull=False
            )
            if not source.candidate_image_id:
                raise ValueError("The attempt has no verified candidate")
            if target.attempt_id:
                DevStackImageAttempt.objects.using("default").filter(
                    pk=target.attempt_id, status__in=["queued", "building", "verifying"]
                ).update(status="superseded", finished_at=timezone.now())
            target.generation += 1
            target.observation_revision += 1
            target.base_reference = source.base_reference
            target.repository_sha = source.repository_sha
            target.recipe_sha = source.recipe_sha
            target.auto_refresh = False
            target.pending_request_key = ""
            target.requested_at = timezone.now()
            target.next_retry_at = None
            target.blocked_reason = ""
            attempt = DevStackImageAttempt.objects.using("default").create(
                target=target,
                generation=target.generation,
                base_reference=source.base_reference,
                repository_sha=source.repository_sha,
                recipe_sha=source.recipe_sha,
                candidate_image_id=source.candidate_image_id,
            )
            target.attempt_id = attempt.id
            target.save()

    def observe(self, revision: int, base_reference: str, repository_sha: str, recipe_sha: str) -> bool:
        with transaction.atomic():
            target = DevStackImageTarget.objects.using("default").select_for_update().get(pk=self.target_id)
            if target.observation_revision != revision or not target.auto_refresh:
                return False
            target.observed_at = timezone.now()
            target.observation_error = ""
            changed = (
                target.base_reference != base_reference
                or target.recipe_sha != recipe_sha
                or bool(target.pending_request_key)
            )
            if changed:
                target.generation += 1
                target.base_reference = base_reference
                target.repository_sha = repository_sha
                target.recipe_sha = recipe_sha
                if target.pending_request_key:
                    target.request_key = target.pending_request_key
                    target.pending_request_key = ""
                target.requested_at = target.observed_at
                target.next_retry_at = None
                target.blocked_reason = ""
                if target.attempt_id:
                    DevStackImageAttempt.objects.using("default").filter(
                        pk=target.attempt_id,
                        status__in=["queued", "building", "verifying"],
                    ).update(status="superseded", finished_at=timezone.now())
                target.attempt_id = None
            target.save()
            return changed

    def _budget_retry_at(self, now: datetime) -> datetime | None:
        started = list(
            DevStackImageAttempt.objects.using("default")
            .filter(target_id=self.target_id, bake_started_at__gt=now - BUDGET_WINDOW)
            .order_by("bake_started_at")
            .values_list("bake_started_at", flat=True)
        )
        oldest = started[-BUILD_BUDGET] if len(started) >= BUILD_BUDGET else None
        return oldest + BUDGET_WINDOW if oldest else None

    def reconcile(self) -> DevStackImageAttempt | None:
        with transaction.atomic():
            target = DevStackImageTarget.objects.using("default").select_for_update().get(pk=self.target_id)
            now = timezone.now()
            if not target.enabled or not target.generation or target.active_generation == target.generation:
                return None
            if target.next_retry_at and now < target.next_retry_at:
                return None
            if target.blocked_reason and target.next_retry_at is None:
                return None
            attempt = (
                DevStackImageAttempt.objects.using("default").filter(pk=target.attempt_id).first()
                if target.attempt_id
                else None
            )
            if attempt and attempt.status == "queued" and now < attempt.created_at + DISPATCH_DEADLINE:
                return attempt
            if attempt and attempt.status in ("building", "verifying"):
                if (
                    attempt.lease_expires_at
                    and now < attempt.lease_expires_at
                    and attempt.deadline_at
                    and now < attempt.deadline_at
                ):
                    return None
            if attempt and attempt.status in ("queued", "building", "verifying"):
                attempt.status = "failed"
                attempt.error = (
                    "Dispatch deadline expired"
                    if attempt.started_at is None
                    else "Worker lease or build deadline expired"
                )
                attempt.finished_at = now
                attempt.save(update_fields=["status", "error", "finished_at"])
            candidate = (
                DevStackImageAttempt.objects.using("default")
                .filter(
                    target_id=self.target_id,
                    generation=target.generation,
                    base_reference=target.base_reference,
                    repository_sha=target.repository_sha,
                    recipe_sha=target.recipe_sha,
                )
                .exclude(candidate_image_id="")
                .exclude(error="Candidate verification failed")
                .order_by("-created_at")
                .first()
            )
            retry_at = self._budget_retry_at(now)
            if retry_at and candidate is None:
                target.blocked_reason = "Bake budget exhausted"
                target.next_retry_at = retry_at
                target.save(update_fields=["blocked_reason", "next_retry_at"])
                return None
            attempt = DevStackImageAttempt.objects.using("default").create(
                target=target,
                generation=target.generation,
                base_reference=target.base_reference,
                repository_sha=target.repository_sha,
                recipe_sha=target.recipe_sha,
                candidate_image_id=candidate.candidate_image_id if candidate else "",
            )
            target.attempt_id = attempt.id
            target.next_retry_at = None
            target.blocked_reason = ""
            target.save(update_fields=["attempt_id", "next_retry_at", "blocked_reason"])
            return attempt

    def claim(self, attempt_id: uuid.UUID, owner: uuid.UUID, run_id: str) -> DevStackImageAttempt | None:
        with transaction.atomic():
            target = DevStackImageTarget.objects.using("default").select_for_update().get(pk=self.target_id)
            attempt = DevStackImageAttempt.objects.using("default").get(pk=attempt_id, target_id=self.target_id)
            now = timezone.now()
            if not target.enabled or target.attempt_id != attempt.id or target.generation != attempt.generation:
                return None
            if self._owns(target, attempt, owner) and attempt.workflow_run_id == run_id:
                return attempt
            if attempt.status != "queued" or now >= attempt.created_at + DISPATCH_DEADLINE:
                return None
            retry_at = self._budget_retry_at(now)
            if retry_at and not attempt.candidate_image_id:
                target.next_retry_at = retry_at
                target.blocked_reason = "Bake budget exhausted"
                target.save(update_fields=["next_retry_at", "blocked_reason"])
                return None
            attempt.owner = owner
            attempt.workflow_run_id = run_id
            attempt.started_at = now
            attempt.bake_started_at = now if not attempt.candidate_image_id else None
            attempt.lease_expires_at = now + LEASE_DURATION
            attempt.deadline_at = now + BUILD_DEADLINE
            attempt.status = "verifying" if attempt.candidate_image_id else "building"
            attempt.save()
            return attempt

    def _owns(self, target: DevStackImageTarget, attempt: DevStackImageAttempt, owner: uuid.UUID) -> bool:
        now = timezone.now()
        return bool(
            target.enabled
            and target.attempt_id == attempt.id
            and target.generation == attempt.generation
            and attempt.owner == owner
            and attempt.status in ("building", "verifying")
            and attempt.lease_expires_at
            and now < attempt.lease_expires_at
            and attempt.deadline_at
            and now < attempt.deadline_at
        )

    def renew(self, attempt_id: uuid.UUID, owner: uuid.UUID) -> bool:
        with transaction.atomic():
            target = DevStackImageTarget.objects.using("default").select_for_update().get(pk=self.target_id)
            attempt = DevStackImageAttempt.objects.using("default").get(pk=attempt_id, target_id=self.target_id)
            if not self._owns(target, attempt, owner):
                return False
            attempt.lease_expires_at = timezone.now() + LEASE_DURATION
            attempt.save(update_fields=["lease_expires_at"])
            return True

    def checkpoint(self, attempt_id: uuid.UUID, owner: uuid.UUID, image_id: str) -> bool:
        with transaction.atomic():
            target = DevStackImageTarget.objects.using("default").select_for_update().get(pk=self.target_id)
            attempt = DevStackImageAttempt.objects.using("default").get(pk=attempt_id, target_id=self.target_id)
            if not self._owns(target, attempt, owner):
                return False
            attempt.candidate_image_id = image_id
            attempt.status = "verifying"
            attempt.save(update_fields=["candidate_image_id", "status"])
            return True

    def activate(self, attempt_id: uuid.UUID, owner: uuid.UUID, image_id: str, agent_version: str) -> bool:
        with transaction.atomic():
            target = DevStackImageTarget.objects.using("default").select_for_update().get(pk=self.target_id)
            attempt = DevStackImageAttempt.objects.using("default").get(pk=attempt_id, target_id=self.target_id)
            if attempt.status == "active":
                return target.active_image_id == image_id and target.active_generation == attempt.generation
            if (
                not self._owns(target, attempt, owner)
                or not image_id
                or not agent_version
                or attempt.status != "verifying"
                or attempt.candidate_image_id != image_id
            ):
                return False
            if (target.base_reference, target.repository_sha, target.recipe_sha) != (
                attempt.base_reference,
                attempt.repository_sha,
                attempt.recipe_sha,
            ):
                return False
            now = timezone.now()
            target.active_image_id = image_id
            target.active_agent_version = agent_version
            target.active_generation = attempt.generation
            target.active_base_reference = attempt.base_reference
            target.active_repository_sha = attempt.repository_sha
            target.active_recipe_sha = attempt.recipe_sha
            target.activated_at = now
            target.blocked_reason = ""
            target.next_retry_at = None
            target.save()
            attempt.status = "active"
            attempt.verified_at = now
            attempt.finished_at = now
            attempt.save(update_fields=["status", "verified_at", "finished_at"])
            return True

    def fail(self, attempt_id: uuid.UUID, owner: uuid.UUID, *, invalid: bool = False) -> None:
        with transaction.atomic():
            target = DevStackImageTarget.objects.using("default").select_for_update().get(pk=self.target_id)
            attempt = DevStackImageAttempt.objects.using("default").get(pk=attempt_id, target_id=self.target_id)
            if not self._owns(target, attempt, owner):
                return
            attempt.status = "failed"
            attempt.error = (
                "Candidate verification failed" if invalid else "Bake failed; inspect the Temporal execution"
            )
            attempt.finished_at = timezone.now()
            attempt.save(update_fields=["status", "error", "finished_at"])
            if invalid:
                target.blocked_reason = attempt.error
                target.next_retry_at = None
            else:
                count = (
                    DevStackImageAttempt.objects.using("default")
                    .filter(target=target, generation=target.generation)
                    .count()
                )
                target.next_retry_at = (
                    timezone.now()
                    + RETRY_DELAYS[min(count - 1, len(RETRY_DELAYS) - 1)]
                    + timedelta(seconds=attempt.id.int % 30)
                )
            target.save(update_fields=["blocked_reason", "next_retry_at"])
