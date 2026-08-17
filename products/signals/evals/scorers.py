"""Scorers for the replay-attribution eval.

Two outcome scorers read the finding envelope out of the agent's final message and check where it
attributed the defect. One mechanism scorer checks whether the agent actually queried the events
around the recording moment, which is what separates a correct attribution from a lucky guess off
the URL. Every scorer self-skips (``score=None``) when its ``expected`` key is absent.
"""

from __future__ import annotations

import re
import json
from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

__all__ = ["AttributionAnyPath", "AttributionTopPath", "RecordingWindowQueried"]

_SQL_TOOL = "execute-sql"
# Where every Hedgebox source path starts, used to trim a clone prefix off an agent's answer.
_REPO_ROOT_SEGMENT = "src"
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
# Session ids the suite seeds are v7 UUIDs; matching the literal in SQL text is enough to tell a
# session-scoped query from an unrelated one.
_SESSION_FILTER_RE = re.compile(r"\$session_id", re.IGNORECASE)


def _candidate_json_blobs(message: str) -> list[str]:
    """The message itself plus any fenced blocks, widest first."""
    blobs = [message.strip()]
    blobs.extend(match.strip() for match in _FENCE_RE.findall(message))
    # A model that prefixes prose still usually leaves one balanced object behind.
    first, last = message.find("{"), message.rfind("}")
    if first != -1 and last > first:
        blobs.append(message[first : last + 1])
    return blobs


def _find_relevant_code_paths(value: Any) -> list[str] | None:
    """Depth-first search for the finding's ``relevant_code_paths``, wherever the envelope put it."""
    if isinstance(value, dict):
        paths = value.get("relevant_code_paths")
        if isinstance(paths, list) and all(isinstance(entry, str) for entry in paths):
            return paths
        for nested in value.values():
            found = _find_relevant_code_paths(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_relevant_code_paths(nested)
            if found is not None:
                return found
    return None


def relevant_code_paths(last_message: str | None) -> list[str] | None:
    """Pull ``relevant_code_paths`` out of the agent's final message, or None when it has none."""
    if not last_message:
        return None
    for blob in _candidate_json_blobs(last_message):
        try:
            parsed = json.loads(blob)
        except (ValueError, TypeError):
            continue
        found = _find_relevant_code_paths(parsed)
        if found is not None:
            return found
    return None


def normalize_path(path: str) -> str:
    """Compare paths by their repo-relative tail, so a clone dir or a `./` prefix doesn't count against a hit.

    Every expected path in this suite sits under Hedgebox's `src/`, so an absolute or
    clone-prefixed answer is trimmed back to the segment that starts there.
    """
    cleaned = path.strip().strip("`").lstrip("/").removeprefix("./")
    segments = cleaned.split("/")
    if _REPO_ROOT_SEGMENT in segments:
        return "/".join(segments[segments.index(_REPO_ROOT_SEGMENT) :])
    return cleaned


def _expected_path(expected: dict | None, key: str) -> str | None:
    entry = (expected or {}).get(key)
    return entry.get("path") if isinstance(entry, dict) else None


class _AttributionScorer(Scorer):
    """Shared parsing for the two outcome scorers; subclasses decide which positions count."""

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        wanted = _expected_path(expected, self._name())
        if not wanted:
            return Score(name=self._name(), score=None, metadata={"reason": "No expected path for this case"})
        paths = relevant_code_paths((output or {}).get("last_message"))
        if paths is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "No relevant_code_paths in the final message"},
            )
        if not paths:
            return Score(name=self._name(), score=0.0, metadata={"reason": "relevant_code_paths was empty"})
        normalized = [normalize_path(path) for path in paths]
        return self._score_paths(wanted=normalize_path(wanted), normalized=normalized, raw=paths)

    def _score_paths(self, *, wanted: str, normalized: list[str], raw: list[str]) -> Score:
        raise NotImplementedError


class AttributionTopPath(_AttributionScorer):
    """Did the agent put the file a human would change first?

    This is the outcome the whole recipe exists for. ``relevant_code_paths`` is documented as
    most-critical-first and downstream work reads position zero, so a right answer buried at
    position three is not the same as a right answer.
    """

    def _name(self) -> str:
        return "attribution_top_path"

    def _score_paths(self, *, wanted: str, normalized: list[str], raw: list[str]) -> Score:
        hit = normalized[0] == wanted
        return Score(
            name=self._name(),
            score=1.0 if hit else 0.0,
            metadata={"wanted": wanted, "got": normalized[0], "all_paths": raw},
        )


class AttributionAnyPath(_AttributionScorer):
    """Did the right file appear anywhere in the list?

    Separates "found it but ranked it wrong" from "never found it", which are different failures:
    the first is a ranking problem in the prompt, the second means the anchor never resolved.
    """

    def _name(self) -> str:
        return "attribution_any_path"

    def _score_paths(self, *, wanted: str, normalized: list[str], raw: list[str]) -> Score:
        hit = wanted in normalized
        return Score(
            name=self._name(),
            score=1.0 if hit else 0.0,
            metadata={"wanted": wanted, "position": normalized.index(wanted) if hit else None, "all_paths": raw},
        )


class RecordingWindowQueried(Scorer):
    """Did the agent query the events around the recording moment at all?

    A case can land the right file by guessing from the URL in the signal, which scores as a hit
    while proving nothing about the recipe. This separates the two, and on the route-only case it
    is the check that the agent looked before falling back rather than skipping straight to it.
    """

    def _name(self) -> str:
        return "recording_window_queried"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        entry = (expected or {}).get(self._name())
        if not isinstance(entry, dict):
            return Score(name=self._name(), score=None, metadata={"reason": "Not checked for this case"})
        session_id = entry.get("session_id")
        raw_log = (output or {}).get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        parser = LogParser.cached(raw_log, initial_prompt=(output or {}).get("prompt", "") or "")
        queries = [
            call.input.get("query", "")
            for call in parser.get_tool_calls(_SQL_TOOL)
            if not call.is_error and isinstance(call.input, dict)
        ]
        matching = [
            query
            for query in queries
            if isinstance(query, str) and session_id and session_id in query and _SESSION_FILTER_RE.search(query)
        ]
        return Score(
            name=self._name(),
            score=1.0 if matching else 0.0,
            metadata={"sql_calls": len(queries), "session_scoped_calls": len(matching)},
        )
