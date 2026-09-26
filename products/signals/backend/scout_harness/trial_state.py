from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, TypeVar, cast

from django.db import transaction
from django.utils import timezone

from pydantic import BaseModel, Field, JsonValue, TypeAdapter

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.tools.runs import _build_task_url
from products.signals.backend.scout_harness.tools.scratchpad import (
    DEFAULT_SCRATCHPAD_SEARCH_LIMIT,
    ScratchpadEntry,
    _clamp_search_limit,
    _project_content,
    _validate_entry,
)

if TYPE_CHECKING:
    from uuid import UUID

SCOUT_TRIAL_METADATA_KEY = "scout_trial"
SCOUT_TRIAL_STATE_KEY = "scout_trial_private"
MAX_SCOUT_TRIAL_STATE_BYTES = 2 * 1024 * 1024

_MEMORY_ADAPTER = TypeAdapter(list[ScratchpadEntry])
_Result = TypeVar("_Result")


class ScoutTrialStateError(ValueError):
    pass


class TrialReport(BaseModel):
    id: str
    source_report_id: str | None = None
    document: dict[str, JsonValue]
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    edits: list[dict[str, JsonValue]] = Field(default_factory=list)
    operator_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: list[dict[str, JsonValue]] = Field(default_factory=list)
    artefacts: list[dict[str, JsonValue]] = Field(default_factory=list)
    content_revision_count: int = 0
    corroboration_count: int = 0


class _TrialState(BaseModel):
    memory: dict[str, ScratchpadEntry | None] = Field(default_factory=dict)
    reports: dict[str, TrialReport] = Field(default_factory=dict)
    report_keys: dict[str, str] = Field(default_factory=dict)
    invalid_reason: str | None = None


@frozen
class CapturedTrialReport:
    report: TrialReport
    idempotent_replay: bool


def initial_trial_state() -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], _TrialState().model_dump(mode="json"))


def is_scout_trial(run: SignalScoutRun) -> bool:
    marker = (run.metadata or {}).get(SCOUT_TRIAL_METADATA_KEY)
    return isinstance(marker, dict) and marker.get("version") == 1


def memory_snapshot(entries: Sequence[ScratchpadEntry]) -> list[dict[str, JsonValue]]:
    return cast(list[dict[str, JsonValue]], _MEMORY_ADAPTER.dump_python(list(entries), mode="json"))


class ScoutTrialStore:
    def __init__(
        self,
        run: SignalScoutRun,
        *,
        initial_memory: Sequence[dict[str, JsonValue]] | None = None,
    ) -> None:
        if not is_scout_trial(run):
            raise ScoutTrialStateError("The scout run does not have a private context.")
        self.run = run
        self._initial_memory = initial_memory

    def _memory_snapshot(self) -> dict[str, ScratchpadEntry]:
        if self._initial_memory is None:
            from products.signals.backend.scout_harness.trial_launch import (
                load_trial_context,  # noqa: PLC0415 -- launch contexts use the private state schema
            )

            context_id = (self.run.metadata or {})[SCOUT_TRIAL_METADATA_KEY].get("context_id")
            if not isinstance(context_id, str):
                raise ScoutTrialStateError("The scout run has no saved context.")
            self._initial_memory = load_trial_context(self.run.team_id, context_id).memory
        entries = _MEMORY_ADAPTER.validate_python(self._initial_memory)
        return {entry.key: entry for entry in entries}

    def _read_state(self) -> _TrialState:
        row = (
            SignalScoutRun.objects.for_team(self.run.team_id)
            .filter(pk=self.run.pk, task_run_id=self.run.task_run_id)
            .values("metadata", "task_run__state")
            .first()
        )
        if row is None:
            raise ScoutTrialStateError("The scout run has no private state.")
        marker = (row["metadata"] or {}).get(SCOUT_TRIAL_METADATA_KEY)
        if not isinstance(marker, dict) or marker.get("version") != 1:
            raise ScoutTrialStateError("The scout run has no private state.")
        state = row["task_run__state"] or {}
        return _TrialState.model_validate(state.get(SCOUT_TRIAL_STATE_KEY, {}))

    def _mutate(
        self, change: Callable[[_TrialState], _Result], *, allow_terminal: bool = False, allow_invalid: bool = False
    ) -> _Result:
        invalid_reason: str | None = None
        with transaction.atomic():
            locked = (
                SignalScoutRun.objects.for_team(self.run.team_id)
                .select_related("task_run")
                .select_for_update(of=("task_run",))
                .get(pk=self.run.pk, task_run_id=self.run.task_run_id)
            )
            if not is_scout_trial(locked) or locked.task_run.team_id != self.run.team_id:
                raise ScoutTrialStateError("The scout run has no private state.")
            if not allow_terminal and locked.task_run.status != "in_progress":
                raise ScoutTrialStateError("The scout run is no longer in progress.")
            state = dict(locked.task_run.state or {})
            private = _TrialState.model_validate(state.get(SCOUT_TRIAL_STATE_KEY, {}))
            if private.invalid_reason and not allow_invalid:
                raise ScoutTrialStateError(private.invalid_reason)
            updated = private.model_copy(deep=True)
            result = change(updated)
            payload = updated.model_dump(mode="json")
            reserved_bytes = min(1024, MAX_SCOUT_TRIAL_STATE_BYTES // 4) if updated.invalid_reason is None else 0
            if (
                len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
                > MAX_SCOUT_TRIAL_STATE_BYTES - reserved_bytes
            ):
                invalid_reason = "The scout run exceeded its private state limit and cannot be compared."
                private.invalid_reason = invalid_reason
                payload = private.model_dump(mode="json")
            state[SCOUT_TRIAL_STATE_KEY] = payload
            locked.task_run.state = state
            locked.task_run.save(update_fields=["state", "updated_at"])
        if invalid_reason:
            raise ScoutTrialStateError(invalid_reason)
        return result

    def invalid_reason(self) -> str | None:
        return self._read_state().invalid_reason

    def invalidate(self, reason: str, *, allow_terminal: bool = False) -> None:
        def change(state: _TrialState) -> None:
            if not state.invalid_reason:
                state.invalid_reason = reason[:200]

        self._mutate(change, allow_terminal=allow_terminal, allow_invalid=True)

    def export(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], self._read_state().model_dump(mode="json"))

    @staticmethod
    def _merge_memory(snapshot: dict[str, ScratchpadEntry], state: _TrialState) -> dict[str, ScratchpadEntry]:
        merged = dict(snapshot)
        for key, entry in state.memory.items():
            if entry is None:
                merged.pop(key, None)
            else:
                merged[key] = entry
        return merged

    def search_memory(
        self,
        *,
        text: str | None = None,
        key: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = DEFAULT_SCRATCHPAD_SEARCH_LIMIT,
        keys_only: bool = False,
        content_max_chars: int | None = None,
        include_expired: bool = False,
    ) -> list[ScratchpadEntry]:
        entries = self._merge_memory(self._memory_snapshot(), self._read_state()).values()
        now = timezone.now()
        result = []
        for entry in entries:
            if key and entry.key != key:
                continue
            if text and text.casefold() not in entry.key.casefold() and text.casefold() not in entry.content.casefold():
                continue
            if not include_expired and entry.expires_at and datetime.fromisoformat(entry.expires_at) <= now:
                continue
            updated_at = datetime.fromisoformat(entry.updated_at) if entry.updated_at else None
            if date_from is not None and (updated_at is None or updated_at < date_from):
                continue
            if date_to is not None and (updated_at is None or updated_at >= date_to):
                continue
            result.append(entry)
        result.sort(key=lambda entry: (entry.updated_at or "", entry.key), reverse=True)
        return [
            replace(
                entry,
                content=_project_content(entry.content, keys_only=keys_only, content_max_chars=content_max_chars),
            )
            for entry in result[: _clamp_search_limit(limit)]
        ]

    def remember(self, *, key: str, content: str, expires_at: datetime | None = None) -> ScratchpadEntry:
        _validate_entry(key=key, content=content, expires_at=expires_at)
        snapshot = self._memory_snapshot()

        def change(state: _TrialState) -> ScratchpadEntry:
            existing = self._merge_memory(snapshot, state).get(key)
            now = timezone.now().isoformat()
            entry = (
                replace(
                    existing, content=content, expires_at=expires_at.isoformat() if expires_at else None, updated_at=now
                )
                if existing is not None
                else ScratchpadEntry(
                    key=key,
                    content=content,
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at.isoformat() if expires_at else None,
                    created_by_run_id=str(self.run.id),
                    created_by_skill=self.run.skill_name,
                    created_by_run_url=_build_task_url(
                        team_id=self.run.team_id,
                        task_id=str(self.run.task_run.task_id),
                        task_run_id=str(self.run.task_run_id),
                    ),
                )
            )
            state.memory[key] = entry
            return entry

        return self._mutate(change)

    def forget(self, *, key: str) -> bool:
        snapshot = self._memory_snapshot()

        def change(state: _TrialState) -> bool:
            if key not in self._merge_memory(snapshot, state):
                return False
            state.memory[key] = None
            return True

        return self._mutate(change)

    def reports(self) -> list[TrialReport]:
        return list(self._read_state().reports.values())

    def get_report(self, report_id: str | UUID) -> TrialReport | None:
        return self._read_state().reports.get(str(report_id))

    def report_for_key(self, idempotency_key: str) -> TrialReport | None:
        state = self._read_state()
        report_id = state.report_keys.get(idempotency_key)
        return state.reports.get(report_id) if report_id is not None else None

    def capture_report(self, report: TrialReport, *, idempotency_key: str) -> CapturedTrialReport:
        def change(state: _TrialState) -> CapturedTrialReport:
            existing_id = state.report_keys.get(idempotency_key)
            if existing_id is not None:
                return CapturedTrialReport(report=state.reports[existing_id], idempotent_replay=True)
            state.reports[report.id] = report
            state.report_keys[idempotency_key] = report.id
            return CapturedTrialReport(report=report, idempotent_replay=False)

        return self._mutate(change)

    def edit_report(
        self,
        report_id: str,
        change: Callable[[TrialReport], _Result],
        *,
        original: TrialReport | None = None,
    ) -> _Result:
        def update(state: _TrialState) -> _Result:
            report = state.reports.get(report_id)
            if report is None:
                if original is None or original.id != report_id or original.source_report_id != report_id:
                    raise ScoutTrialStateError("The report is not available to this scout run.")
                report = original.model_copy(deep=True)
                state.reports[report_id] = report
            return change(report)

        return self._mutate(update)
