import hashlib
from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.db.models import DateTimeField, F
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.tasks.backend.models import TaskRun
from products.tasks.backend.stale_runs import NO_PROFILE, SweepMode, modes_for

logger = structlog.get_logger(__name__)

FENCING_FLAG = "tasks-ended-run-fencing"
TOKEN_HASHES_STATE_KEY = "gateway_token_hashes"
ENDED_WITHIN = timedelta(hours=1)
MAX_TOKENS_PER_RUN = 20
MAX_HASHES_PER_REVOKE = 100
_ENDED_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)


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


def record_run_gateway_token(run_id: UUID | str, token: str) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    def remember(state: dict[str, Any]) -> None:
        state[TOKEN_HASHES_STATE_KEY] = [*state.get(TOKEN_HASHES_STATE_KEY, []), token_hash][-MAX_TOKENS_PER_RUN:]

    TaskRun.mutate_state_atomic(run_id, remember)


def _forget_run_gateway_tokens(run_id: UUID, token_hashes: tuple[str, ...]) -> None:
    revoked = set(token_hashes)

    def forget(state: dict[str, Any]) -> None:
        left = [token_hash for token_hash in state.get(TOKEN_HASHES_STATE_KEY, []) if token_hash not in revoked]
        if left:
            state[TOKEN_HASHES_STATE_KEY] = left
        else:
            state.pop(TOKEN_HASHES_STATE_KEY, None)

    TaskRun.mutate_state_atomic(run_id, forget)


def ended_runs_with_tokens() -> list[EndedRunTokens]:
    ended = (
        TaskRun.objects.filter(
            status__in=_ENDED_STATUSES,
            environment=TaskRun.Environment.CLOUD,
            state__has_key=TOKEN_HASHES_STATE_KEY,
        )
        .annotate(ended_at=Coalesce(F("completed_at"), F("updated_at"), output_field=DateTimeField()))
        .filter(ended_at__gte=timezone.now() - ENDED_WITHIN)
        .order_by()
        .values_list("id", "team_id", "task__profile", f"state__{TOKEN_HASHES_STATE_KEY}")
    )
    return [
        EndedRunTokens(run_id=run_id, team_id=team_id, profile=profile, token_hashes=tuple(token_hashes))
        for run_id, team_id, profile, token_hashes in ended
        if token_hashes
    ]


def _batches(runs: list[EndedRunTokens]) -> list[list[EndedRunTokens]]:
    batches: list[list[EndedRunTokens]] = []
    size = 0
    for run in runs:
        if not batches or size + len(run.token_hashes) > MAX_HASHES_PER_REVOKE:
            batches.append([])
            size = 0
        batches[-1].append(run)
        size += len(run.token_hashes)
    return batches


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
        if not revoke([token_hash for run in batch for token_hash in run.token_hashes]):
            logger.warning("task_run_token_fencing_revoke_failed", runs=len(batch))
            continue
        for run in batch:
            _forget_run_gateway_tokens(run.run_id, run.token_hashes)
            counts[(run.profile or NO_PROFILE, FenceOutcome.REVOKED)] += len(run.token_hashes)
    return [FencedTokens(profile=profile, outcome=outcome, count=count) for (profile, outcome), count in counts.items()]
