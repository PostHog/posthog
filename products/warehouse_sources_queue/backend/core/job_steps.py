"""Step checkpoints for workflow jobs: SQL and row types for ``queuejobstep``.

A workflow job runs its function again on each attempt. Each step that ends writes one row
here, so a later attempt reads the rows and does not run a completed step again. The table is
append-only: a failed execution adds a ``failed`` row, and a completed step adds one
``succeeded`` or ``skipped`` row, which a partial unique index keeps to one per step.

The table is partitioned on the job's ``created_at`` (``job_created_at``), so the rows of one
job sit in one partition and leave with the job's own partition at retention.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

import psycopg
from psycopg.rows import dict_row

from posthog.dataclasses import frozen

from products.warehouse_sources_queue.backend.core.batch_consumer import OwnershipLostError
from products.warehouse_sources_queue.backend.core.generic_jobs import JOB_TABLE

JOB_STEP_TABLE = "queuejobstep"
STEP_KEY_MAX_LENGTH = 200
STEP_ERROR_MAX_LENGTH = 4000


class StepState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


COMPLETED_STEP_STATES = (StepState.SUCCEEDED, StepState.SKIPPED)


@frozen
class StepRecord:
    """One row of a job's step log."""

    key: str
    state: StepState
    job_attempt: int
    started_at: datetime
    ended_at: datetime
    # The step's return value as JSON. None for a failed or skipped step.
    result: Any
    error: str | None


# The fence locks the job row in share mode, so a status write (which takes the row FOR UPDATE)
# waits for the step write, and the step write re-checks the row after any status write it waited
# on. A zombie attempt therefore cannot record a step after the job moved to another attempt.
_FENCED_INSERT_SQL = f"""
    WITH owner AS (
        SELECT 1
        FROM {JOB_TABLE} j
        WHERE j.id = %(job_id)s
          AND j.created_at = %(job_created_at)s
          AND j.latest_state = 'executing'
          AND j.latest_attempt = %(job_attempt)s
        FOR SHARE OF j
    )
    INSERT INTO {JOB_STEP_TABLE} (
        job_id, job_created_at, step_key, state, job_attempt, started_at, ended_at, result, error
    )
    SELECT
        %(job_id)s, %(job_created_at)s, %(step_key)s, %(state)s, %(job_attempt)s,
        %(started_at)s, %(ended_at)s, %(result)s::jsonb, %(error)s
    FROM owner
    RETURNING id
"""


class JobStepsTable:
    """Raw SQL over ``queuejobstep`` (the ``JobsTable`` idiom)."""

    @staticmethod
    async def load(
        conn: psycopg.AsyncConnection[Any],
        *,
        job_id: str,
        job_created_at: datetime,
    ) -> list[StepRecord]:
        """Every step row of one job, in the order the steps ended."""
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT step_key, state, job_attempt, started_at, ended_at, result, error
                FROM {JOB_STEP_TABLE}
                WHERE job_id = %(job_id)s AND job_created_at = %(job_created_at)s
                ORDER BY job_attempt ASC, ended_at ASC, id ASC
                """,
                {"job_id": job_id, "job_created_at": job_created_at},
            )
            rows = await cur.fetchall()
        return [
            StepRecord(
                key=row["step_key"],
                state=StepState(row["state"]),
                job_attempt=row["job_attempt"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                result=row["result"],
                error=row["error"],
            )
            for row in rows
        ]

    @staticmethod
    async def record(
        conn: psycopg.AsyncConnection[Any],
        *,
        job_id: str,
        job_created_at: datetime,
        record: StepRecord,
        encoded_result: str | None = None,
    ) -> None:
        """Write one step row, fenced on the job's current attempt.

        ``encoded_result`` is the JSON text of the result. The caller encodes it, because the
        caller also enforces the size cap on the same bytes. Raises ``OwnershipLostError`` when
        the job is no longer executing this attempt.
        """
        cursor = await conn.execute(
            _FENCED_INSERT_SQL,
            {
                "job_id": job_id,
                "job_created_at": job_created_at,
                "step_key": record.key,
                "state": record.state.value,
                "job_attempt": record.job_attempt,
                "started_at": record.started_at,
                "ended_at": record.ended_at,
                "result": encoded_result,
                "error": record.error[:STEP_ERROR_MAX_LENGTH] if record.error is not None else None,
            },
        )
        if await cursor.fetchone() is None:
            raise OwnershipLostError(
                f"job {job_id} is no longer executing attempt {record.job_attempt}; refusing to record step {record.key!r}"
            )
