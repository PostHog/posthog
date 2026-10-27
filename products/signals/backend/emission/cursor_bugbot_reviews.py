"""Signal emitter for cursor `bugbot_reviews` (record kind: issue).

One row is one completed Bugbot review of a pull request.
Dry runs post nothing, so the query and the emitter skip them, and so they skip reviews with no findings.
A posted review lists only the severity and resolution status of each finding.
A finding has a title and a description only when the API returns them, so the text is optional.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra, parse_json_list
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

CURSOR_BUGBOT_FIELDS = (
    "request_id",
    "timestamp",
    "repo",
    "pr_number",
    "commit_sha",
    "bugs_found",
    "dry_run",
    "publication_status",
    "bugs",
)

_EXTRA_FIELDS = ("repo", "pr_number", "commit_sha", "bugs_found", "publication_status", "timestamp")
_SEVERITY_ORDER = ("critical", "high", "medium", "low")
_MAX_LISTED_BUGS = 10
_MAX_BUG_DESCRIPTION_CHARS = 200
_TRUE_VALUES = ("true", "1")


def _bug_lines(bugs: list[Any]) -> list[str]:
    lines: list[str] = []
    for bug in bugs:
        if not isinstance(bug, dict):
            continue
        title = clean_text(bug.get("title"))
        if not title:
            continue
        severity = clean_text(bug.get("severity"))
        line = f"- [{severity}] {title}" if severity else f"- {title}"
        if description := clean_text(bug.get("description")):
            line += f": {description[:_MAX_BUG_DESCRIPTION_CHARS]}"
        lines.append(line)
        if len(lines) >= _MAX_LISTED_BUGS:
            break
    return lines


def cursor_bugbot_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    request_id = clean_text(record.get("request_id"))
    if not request_id:
        return None
    if clean_text(record.get("dry_run")).lower() in _TRUE_VALUES:
        return None
    try:
        bugs_found = int(clean_text(record.get("bugs_found")) or 0)
    except ValueError:
        bugs_found = 0
    if bugs_found <= 0:
        logger.info(
            "Ignoring cursor bugbot review without findings",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    bugs = parse_json_list(record.get("bugs"))
    statuses = [clean_text(bug.get("resolution_status")).lower() for bug in bugs if isinstance(bug, dict)]
    if statuses and all(status == "resolved" for status in statuses):
        return None
    repo = clean_text(record.get("repo"))
    pr_number = clean_text(record.get("pr_number"))
    target = " ".join(part for part in (repo, f"PR #{pr_number}" if pr_number else "") if part)
    noun = "issue" if bugs_found == 1 else "issues"
    lines = [
        f"Cursor Bugbot found {bugs_found} {noun} in {target}" if target else f"Cursor Bugbot found {bugs_found} {noun}"
    ]
    severities = [clean_text(bug.get("severity")).lower() for bug in bugs if isinstance(bug, dict)]
    # Known levels come first in a fixed order, then any other level the API returns.
    levels = [*_SEVERITY_ORDER, *sorted({level for level in severities if level and level not in _SEVERITY_ORDER})]
    breakdown = ", ".join(f"{severities.count(level)} {level}" for level in levels if severities.count(level) > 0)
    if breakdown:
        lines.append(f"Severity: {breakdown}")
    unresolved = statuses.count("unresolved")
    if unresolved:
        lines.append(f"Unresolved: {unresolved}")
    if commit_sha := clean_text(record.get("commit_sha")):
        lines.append(f"Commit: {commit_sha}")
    lines.extend(_bug_lines(bugs))
    return SignalEmitterOutput(
        source_product="cursor",
        source_type="issue",
        source_id=request_id,
        description="\n".join(lines),
        weight=1.0,
        extra=build_extra(record, _EXTRA_FIELDS, ()),
    )


CURSOR_CONFIG = SignalSourceTableConfig(
    source_product="cursor",
    source_type="issue",
    emitter=cursor_bugbot_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="timestamp",
    partition_field_is_datetime_string=True,
    fields=CURSOR_BUGBOT_FIELDS,
    where_clause="bugs_found > 0 AND toString(dry_run) NOT IN ('true', '1')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
