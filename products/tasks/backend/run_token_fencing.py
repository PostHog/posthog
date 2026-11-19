import re
import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.db.models import DateTimeField, F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.tasks.backend.models import TaskRun
from products.tasks.backend.stale_runs import NO_PROFILE, SweepMode, modes_for

logger = structlog.get_logger(__name__)

FENCING_FLAG = "tasks-ended-run-fencing"
TOKEN_HASHES_STATE_KEY = "gateway_token_hashes"
REVOKE_PENDING_STATE_KEY = "gateway_token_revoke_pending"
ENDED_WITHIN = timedelta(hours=1)
REVOKE_RETRY_WINDOW = timedelta(hours=24)
MAX_HASHES_PER_REVOKE = 100
_ENDED_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)
_TOKEN_HASH = re.compile(r"[0-9a-f]{64}")


class FenceOutcome(StrEnum):
    REVOKED = "revoked"
    WOULD_REVOKE = "would_revoke"


@frozen
class EndedRunTokens:
    run_id: UUID
    team_id: int
    profile: str | None
    token_hashes: tuple[str, ...]


@frozen
class FencedTokens:
    profile: str
    outcome: FenceOutcome
    count: int


def _stored_hashes(stored: object) -> tuple[str, ...]:
    if not isinstance(stored, list):
        return ()
    return tuple(value for value in stored if isinstance(value, str) and _TOKEN_HASH.fullmatch(value))


def record_run_gateway_token(run_id: UUID | str, token: str) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    def remember(state: dict[str, Any]) -> None:
        state[TOKEN_HASHES_STATE_KEY] = [*_stored_hashes(state.get(TOKEN_HASHES_STATE_KEY)), token_hash]

    TaskRun.mutate_state_atomic(run_id, remember)


def _forget_run_gateway_tokens(run_id: UUID, token_hashes: list[str]) -> None:
    revoked = set(token_hashes)

    def forget(state: dict[str, Any]) -> None:
        stored = _stored_hashes(state.get(TOKEN_HASHES_STATE_KEY))
        left = [token_hash for token_hash in stored if token_hash not in revoked]
        if left:
            state[TOKEN_HASHES_STATE_KEY] = left
        else:
            state.pop(TOKEN_HASHES_STATE_KEY, None)
            state.pop(REVOKE_PENDING_STATE_KEY, None)

    TaskRun.mutate_state_atomic(run_id, forget)


def _keep_for_retry(run_id: UUID) -> None:
    def mark(state: dict[str, Any]) -> None:
        state[REVOKE_PENDING_STATE_KEY] = True

    TaskRun.mutate_state_atomic(run_id, mark)


def ended_runs_with_tokens() -> list[EndedRunTokens]:
    now = timezone.now()
    ended = (
        TaskRun.objects.filter(
            status__in=_ENDED_STATUSES,
            environment=TaskRun.Environment.CLOUD,
            state__has_key=TOKEN_HASHES_STATE_KEY,
        )
        .annotate(ended_at=Coalesce(F("completed_at"), F("updated_at"), output_field=DateTimeField()))
        .filter(
            Q(ended_at__gte=now - ENDED_WITHIN)
            | Q(ended_at__gte=now - REVOKE_RETRY_WINDOW, state__has_key=REVOKE_PENDING_STATE_KEY)
        )
        .order_by()
        .values_list("id", "team_id", "task__profile", f"state__{TOKEN_HASHES_STATE_KEY}")
    )
    return [
        EndedRunTokens(run_id=run_id, team_id=team_id, profile=profile, token_hashes=token_hashes)
        for run_id, team_id, profile, stored in ended
        if (token_hashes := _stored_hashes(stored))
    ]


def _batches(runs: list[EndedRunTokens]) -> list[list[tuple[EndedRunTokens, str]]]:
    hashes = [(run, token_hash) for run in runs for token_hash in run.token_hashes]
    return [hashes[start : start + MAX_HASHES_PER_REVOKE] for start in range(0, len(hashes), MAX_HASHES_PER_REVOKE)]


def fence_ended_runs(revoke: Callable[[list[str]], bool]) -> list[FencedTokens]:
    ended = ended_runs_with_tokens()
    if not ended:
        return []
    modes = modes_for(FENCING_FLAG, {(run.team_id, run.profile) for run in ended})
    counts: Counter[tuple[str, FenceOutcome]] = Counter()
    enforced: list[EndedRunTokens] = []
    for run in ended:
        mode = modes.get((run.team_id, run.profile), SweepMode.OFF)
        if mode == SweepMode.ENFORCE:
            enforced.append(run)
        elif mode == SweepMode.SHADOW:
            counts[(run.profile or NO_PROFILE, FenceOutcome.WOULD_REVOKE)] += len(run.token_hashes)
    for batch in _batches(enforced):
        if not revoke([token_hash for _, token_hash in batch]):
            logger.warning("task_run_fencing_revoke_failed", hashes=len(batch))
            for run_id in {run.run_id for run, _ in batch}:
                _keep_for_retry(run_id)
            continue
        revoked: defaultdict[UUID, list[str]] = defaultdict(list)
        for run, token_hash in batch:
            revoked[run.run_id].append(token_hash)
            counts[(run.profile or NO_PROFILE, FenceOutcome.REVOKED)] += 1
        for run_id, token_hashes in revoked.items():
            _forget_run_gateway_tokens(run_id, token_hashes)
    return [FencedTokens(profile=profile, outcome=outcome, count=count) for (profile, outcome), count in counts.items()]
