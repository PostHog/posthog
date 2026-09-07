"""Scorers and tool groups shared by the feature-flags eval suites."""

from __future__ import annotations

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

# Claude's named file tools. The codex runtime does not carry them, which is why the
# suites that grade edit direction refuse codex runs (see seeders._require_claude_runtime).
FILE_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})

# The read tools the cleanup skill's assessment steps go through. A run that never calls
# any of them decided about the seeded flag without looking at it.
FLAG_LOOKUP_TOOLS = frozenset(
    {
        "feature-flag-get-all",
        "feature-flags-status-retrieve",
        "feature-flag-get-definition",
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
            metadata={self._key: wanted, "calls": calls[:10]},
        )


class FlagStateUnchanged(Scorer):
    """Binary: is the seeded flag's stored state identical after the run?

    ``no_flag_mutation`` matches tool names, and the sandbox token is not read-only,
    so a write that bypasses the MCP surface (curl against the API) scores green there.
    This scorer re-reads the row instead, so any write path shows up.

    Reloads via ``objects_including_soft_deleted``: ``objects`` hides soft-deleted rows,
    so ``objects.get`` would raise exactly when the agent deleted the flag.
    Skips (``None``) on cases whose seed carries no flag, so one scorer list spans the suite.
    """

    _WATCHED_FIELDS = ("key", "active", "deleted", "archived", "filters")

    def _name(self) -> str:
        return "flag_state_unchanged"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        seed = (output or {}).get("seed") or {}
        flag_id, seeded_state = seed.get("flag_id"), seed.get("state")
        if not flag_id or not isinstance(seeded_state, dict):
            return Score(name=self._name(), score=None, metadata={"reason": "No seeded flag state"})

        try:
            flag = FeatureFlag.objects_including_soft_deleted.get(pk=flag_id)
        except FeatureFlag.DoesNotExist:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Flag row is gone"})

        changed = {
            field: getattr(flag, field)
            for field in self._WATCHED_FIELDS
            if field in seeded_state and getattr(flag, field) != seeded_state[field]
        }
        if changed:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"changed_fields": {field: repr(value) for field, value in changed.items()}},
            )
        return Score(name=self._name(), score=1.0, metadata={})
