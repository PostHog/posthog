from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from django.utils import timezone

from pydantic import TypeAdapter

from products.signals.backend.scout_harness.tools.notes import MAX_NOTES_LIST_LIMIT, ScoutNote
from products.signals.backend.scout_harness.tools.runs import MAX_RUN_SEARCH_LIMIT, RunSummary
from products.signals.backend.scout_harness.trial_launch import TrialContext


def _within_dates(value: str | None, date_from: datetime | None, date_to: datetime | None) -> bool:
    parsed = datetime.fromisoformat(value) if value else None
    return not (
        (date_from is not None and (parsed is None or parsed < date_from))
        or (date_to is not None and (parsed is None or parsed >= date_to))
    )


class SavedScoutReads:
    def __init__(self, context: TrialContext) -> None:
        self.context = context

    def notes(
        self,
        *,
        skill_name: str | None = None,
        include_general: bool = True,
        include_expired: bool = False,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 20,
        content_max_chars: int | None = None,
        exclude_origins: Sequence[str] = (),
    ) -> list[ScoutNote]:
        rows = TypeAdapter(list[ScoutNote]).validate_python(self.context.notes)
        now = timezone.now()
        selected = []
        for row in rows:
            if (
                skill_name is not None
                and row.skill_name != skill_name
                and not (include_general and row.skill_name == "")
            ):
                continue
            if row.origin in exclude_origins or not _within_dates(row.created_at, date_from, date_to):
                continue
            if not include_expired and row.expires_at and datetime.fromisoformat(row.expires_at) <= now:
                continue
            selected.append(
                replace(row, content=row.content[:content_max_chars]) if content_max_chars is not None else row
            )
        return selected[: max(1, min(limit, MAX_NOTES_LIST_LIMIT))]

    def recent_runs(
        self,
        live: list[RunSummary],
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        text: str | None = None,
        emitted: bool | None = None,
        skill_name: str | None = None,
        skill_version: int | None = None,
        limit: int = 20,
    ) -> list[RunSummary]:
        selected = [row for row in live if row.skill_name != self.context.skill_name]
        for row in TypeAdapter(list[RunSummary]).validate_python(self.context.recent_runs):
            if skill_name is not None and row.skill_name != skill_name:
                continue
            if skill_version is not None and row.skill_version != skill_version:
                continue
            if not _within_dates(row.created_at, date_from, date_to):
                continue
            if text and text.casefold() not in row.summary.casefold():
                continue
            if emitted is not None and bool(row.emitted_count or row.emitted_report_ids) != emitted:
                continue
            selected.append(row)
        selected.sort(key=lambda row: row.created_at, reverse=True)
        return selected[: max(1, min(limit, MAX_RUN_SEARCH_LIMIT))]
