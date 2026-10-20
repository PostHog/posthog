"""Overlap policies: when a scheduled fire may enqueue a job for a group.

The queue serializes jobs per ``(lane, group_key)``, so two jobs of one group
never run at the same time. An overlap policy only decides whether a new job
may join the group while earlier jobs are still live. The two policies match
the Temporal schedule overlap policies of the same name under that
serialization. The SQL that reads the live state lives in ``generic_jobs.py``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import assert_never

from posthog.dataclasses import frozen


class OverlapPolicy(StrEnum):
    # Fire only when the group has no live job: none pending and none running.
    SKIP = "skip"
    # Fire when the group has no pending job. A running job does not block,
    # because the new job waits behind it. At most one job is buffered.
    BUFFER_ONE = "buffer_one"


@frozen
class GroupJobState:
    """The live jobs of one group, as the overlap policies see them.

    ``has_pending``: a live job that no consumer has claimed yet.
    ``has_running``: a live job that a consumer claimed and has not finished,
    including one that waits for its next retry attempt.
    """

    has_running: bool = False
    has_pending: bool = False


def overlap_allows(policy: OverlapPolicy, state: GroupJobState) -> bool:
    match policy:
        case OverlapPolicy.SKIP:
            return not state.has_running and not state.has_pending
        case OverlapPolicy.BUFFER_ONE:
            return not state.has_pending
        case _:
            assert_never(policy)
