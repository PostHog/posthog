"""
Business logic for hogbot.

Validation, calculations, business rules, ORM queries.
Called by facade/api.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime

from django.conf import settings

from posthog.storage import object_storage


def get_admin_log_key(team_id: int) -> str:
    return f"{settings.OBJECT_STORAGE_HOGBOT_FOLDER}/logs/hogbot_{team_id}_admin.jsonl"


def get_research_log_key(team_id: int, signal_id: str) -> str:
    return f"{settings.OBJECT_STORAGE_HOGBOT_FOLDER}/logs/hogbot_{team_id}_{signal_id}.jsonl"


def append_log_entries(key: str, team_id: int, entries: Iterable[dict]) -> None:
    serialized_entries = [json.dumps(entry) for entry in entries]
    if not serialized_entries:
        return

    existing_content = object_storage.read(key, missing_ok=True) or ""
    is_new_file = not existing_content
    new_lines = "\n".join(serialized_entries)
    content = existing_content + ("\n" if existing_content else "") + new_lines
    object_storage.write(key, content)

    if is_new_file:
        try:
            object_storage.tag(
                key,
                {
                    "ttl_days": "30",
                    "team_id": str(team_id),
                },
            )
        except Exception:
            # Tags are best-effort and should not block log persistence.
            pass


def read_log_entries(
    key: str,
    *,
    after: datetime | None = None,
    event_types: set[str] | None = None,
    exclude_types: set[str] | None = None,
    limit: int = 1000,
) -> tuple[list[dict], int]:
    log_content = object_storage.read(key, missing_ok=True) or ""
    if not log_content.strip():
        return [], 0

    all_entries: list[dict] = []
    for line in log_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            all_entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    filtered: list[dict] = []
    for entry in all_entries:
        if after:
            entry_ts = entry.get("timestamp", "")
            if not entry_ts:
                continue
            try:
                entry_dt = datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if entry_dt <= after:
                continue

        event_type = get_event_type(entry)
        if event_types and event_type not in event_types:
            continue
        if exclude_types and event_type in exclude_types:
            continue

        filtered.append(entry)
        if len(filtered) >= limit:
            break

    return filtered, len(all_entries)


def get_event_type(entry: dict) -> str:
    notification = entry.get("notification", {})
    if not isinstance(notification, dict):
        return ""
    return str(notification.get("method", ""))
