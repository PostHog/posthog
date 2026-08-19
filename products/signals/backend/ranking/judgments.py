"""Latest priority / actionability judgment per report, read from the artefact log.

Shared by the dataset dag's report-state snapshot and the scoring sweep: the two must agree on
what "the report's priority" means at a moment in time, or the model trains on one definition and
serves on another.
"""

import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReportArtefact

# Stay far below Postgres's 65,535 bind-parameter cap when expanding id__in filters.
ORM_ID_CHUNK = 10_000


def chunked(ids: list[str]) -> Iterator[list[str]]:
    for offset in range(0, len(ids), ORM_ID_CHUNK):
        yield ids[offset : offset + ORM_ID_CHUNK]


@frozen
class Judgment:
    priority: str | None = None
    actionability: str | None = None


def _judgment_value(parsed: dict[str, Any], key: str) -> str | None:
    # Legacy artefact content is unconstrained JSON; a non-string value must not reach a string
    # column or the feature vector.
    value = parsed.get(key)
    return value if isinstance(value, str) else None


def latest_judgments(report_ids: list[str], as_of: datetime) -> dict[str, Judgment]:
    """Latest priority/actionability judgment per report as of `as_of`, parsed from the artefact
    content JSON.

    Artefacts are appended in normal operation but the API permits editing one in place
    (`update_content` rewrites content and bumps updated_at, leaving created_at alone), so a row's
    current content is not necessarily what it held at the cutoff. The latest pre-cutoff row is
    therefore chosen first and then nulled if it was edited afterwards: skipping edited rows during
    selection instead would hand back the judgment they superseded, which was already stale at the
    cutoff - silently wrong where null is merely unknown.
    """
    judgments: dict[str, dict[str, str | None]] = {}
    for chunk in chunked(report_ids):
        artefacts = (
            SignalReportArtefact.objects.filter(
                report_id__in=chunk,
                type__in=[
                    SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                    SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                ],
                created_at__lt=as_of,
            )
            .order_by("report_id", "type", "-created_at")
            .distinct("report_id", "type")
            .values_list("report_id", "type", "content", "updated_at")
        )
        for report_id, artefact_type, content, updated_at in artefacts.iterator(chunk_size=2000):
            # A null updated_at is a row predating the field, never an edit.
            if updated_at is not None and updated_at >= as_of:
                continue
            try:
                parsed = json.loads(content)
            except ValueError:
                continue
            # Legacy artefact rows can hold JSON that is not an object; readers tolerate them.
            if not isinstance(parsed, dict):
                continue
            entry = judgments.setdefault(str(report_id), {"priority": None, "actionability": None})
            if artefact_type == SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT:
                entry["priority"] = _judgment_value(parsed, "priority")
            else:
                entry["actionability"] = _judgment_value(parsed, "actionability")
    return {report_id: Judgment(**entry) for report_id, entry in judgments.items()}
