"""Scorers and tool groups shared by the feature-flags eval suites."""

from __future__ import annotations

import asyncio
from typing import Any

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers import AsyncOnlyScorerMixin
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

# Claude's named file tools. The codex runtime does not carry them, which is why the
# suites that grade edit direction refuse codex runs (see seeders._require_claude_runtime).
FILE_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})

# The read tools the cleanup skill's assessment steps go through. A run that never calls
# any of them decided about the seeded flag without looking at it. The by-key variant is
# here because it is the lookup the MCP surface steers an agent toward when a prompt hands
# it a flag key and no numeric id.
FLAG_LOOKUP_TOOLS = frozenset(
    {
        "feature-flag-get-all",
        "feature-flags-status-retrieve",
        "feature-flag-get-definition",
        "feature-flag-get-definition-by-key",
    }
)

# The reads behind the skill's dependency and schedule exclusions, one group per scorer
# so each read is graded on its own: folded into one any-of group, a run that skipped the
# schedule read would still score green. Kept out of FLAG_LOOKUP_TOOLS for the same reason.
DEPENDENTS_READ_TOOLS = frozenset({"feature-flags-dependent-flags-retrieve"})
SCHEDULE_READ_TOOLS = frozenset({"scheduled-changes-list"})

# Every write verb the current MCP surface offers for a flag. The cleanup skill must not
# call any of them on any case — it never changes a flag, and archival belongs to a
# deployment-confirmed continuation. A test binds this set to tools.yaml so a new write
# verb cannot slip past it.
FLAG_MUTATION_TOOLS = frozenset(
    {
        "feature-flag-archive",
        "feature-flag-unarchive",
        "feature-flag-disable",
        "feature-flag-enable",
        "delete-feature-flag",
        "update-feature-flag",
        "create-feature-flag",
        "feature-flags-bulk-delete-create",
        "feature-flags-bulk-update-tags-create",
        "feature-flags-copy-flags-create",
        "scheduled-changes-create",
        "scheduled-changes-update",
        "scheduled-changes-delete",
    }
)


class ToolGroupDirection(Scorer):
    """Binary: did the agent's use of a tool group match the direction the case expects?

    ``expected[<name>] = {<key>: <bool>}`` on every case; an undeclared direction
    skips rather than assuming one. Counts only successful calls, so a failed
    attempt doesn't flip a negative case.
    """

    _tools: frozenset[str]
    _label: str
    _key: str

    def __init__(self, tools: frozenset[str], *, name: str, key: str) -> None:
        self._tools = tools
        self._label = name
        self._key = key

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if not output or not output.get("raw_log"):
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        direction = (expected or {}).get(self._name())
        if not isinstance(direction, dict) or self._key not in direction:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._key} declared"})

        parser = LogParser.cached(output["raw_log"], initial_prompt=output.get("prompt", "") or "")
        calls = [call.name for call in parser.get_tool_calls() if not call.is_error and call.name in self._tools]
        wanted = bool(direction[self._key])
        return Score(
            name=self._name(),
            score=1.0 if bool(calls) == wanted else 0.0,
            metadata={self._key: wanted, "call_count": len(calls), "calls": calls[:10]},
        )


# The fields a cleanup run must leave unchanged: the contract the seeders snapshot and
# FlagStateUnchanged compares.
WATCHED_FLAG_FIELDS = ("key", "active", "deleted", "archived", "filters")


def read_flag_state(flag_id: int) -> dict[str, Any] | None:
    """Snapshot the watched fields of a flag row, soft-deleted rows included.

    Reads via ``objects_including_soft_deleted``: ``objects`` hides soft-deleted rows,
    so a scorer using it would raise exactly when the agent deleted the flag.
    """
    flag = FeatureFlag.objects_including_soft_deleted.filter(pk=flag_id).first()
    if flag is None:
        return None
    return {field: getattr(flag, field) for field in WATCHED_FLAG_FIELDS}


class FlagStateUnchanged(AsyncOnlyScorerMixin, Scorer):
    """Binary: is the seeded flag's stored state identical after the run?

    ``no_flag_mutation`` matches tool names, and the sandbox token is not read-only,
    so a write that bypasses the MCP surface (curl against the API) scores green there.
    This scorer re-reads the row instead, so any write path shows up.

    The row read runs through ``asyncio.to_thread``: the engine awaits scorers on the
    event loop, where a sync ORM call raises ``SynchronousOnlyOperation``.
    Skips (``None``) on cases whose seed carries no flag, so one scorer list spans the suite.
    """

    def _name(self) -> str:
        return "flag_state_unchanged"

    async def _run_eval_async(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        seed = (output or {}).get("seed") or {}
        flag_id, seeded_state = seed.get("flag_id"), seed.get("state")
        if not flag_id or not isinstance(seeded_state, dict):
            return Score(name=self._name(), score=None, metadata={"reason": "No seeded flag state"})

        current = await asyncio.to_thread(read_flag_state, flag_id)
        return self._score_state(seeded_state, current)

    def _score_state(self, seeded_state: dict[str, Any], current: dict[str, Any] | None) -> Score:
        if current is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Flag row is gone"})
        changed = {
            field: current[field]
            for field in WATCHED_FLAG_FIELDS
            if field in seeded_state and current[field] != seeded_state[field]
        }
        if changed:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"changed_fields": {field: repr(value) for field, value in changed.items()}},
            )
        return Score(name=self._name(), score=1.0, metadata={})
