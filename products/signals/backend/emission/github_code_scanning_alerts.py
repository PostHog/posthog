"""Signal emitter for GitHub `code_scanning_alerts` (record kind: scanner_finding).

The text is in nested JSON: `rule` (description and severity), `tool` (the analyzer) and
`most_recent_instance` (the message and the file location). `dismissed_by` is a user object and is
not selected. Only open alerts emit: the documented states are `open`, `dismissed` and `fixed`.
"""

from typing import Any

from products.signals.backend.emission._github_alerts import alert_text, build_github_alert_output
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

SOURCE_PRODUCT = "github_code_scanning"
MAX_RULE_DESCRIPTION_CHARS = 1500

CODE_SCANNING_FIELDS = (
    "html_url",
    "number",
    "state",
    "created_at",
    "JSONExtractString(toString(rule), 'id') AS rule_id",
    "JSONExtractString(toString(rule), 'description') AS rule_description",
    "JSONExtractString(toString(rule), 'full_description') AS rule_full_description",
    "JSONExtractString(toString(rule), 'severity') AS rule_severity",
    "JSONExtractString(toString(rule), 'security_severity_level') AS security_severity_level",
    "JSONExtractString(toString(tool), 'name') AS tool_name",
    "JSONExtractString(toString(most_recent_instance), 'message', 'text') AS message_text",
    "JSONExtractString(toString(most_recent_instance), 'location', 'path') AS location_path",
    # start_line is a JSON number, which JSONExtractString returns as ''.
    "JSONExtractRaw(toString(most_recent_instance), 'location', 'start_line') AS location_start_line",
)

CODE_SCANNING_EXTRA_FIELDS = (
    "number",
    "state",
    "rule_id",
    "rule_severity",
    "security_severity_level",
    "tool_name",
    "location_path",
    "location_start_line",
    "html_url",
    "created_at",
)


def _location_line(record: dict[str, Any]) -> str | None:
    path = alert_text(record.get("location_path"))
    if not path:
        return None
    line = alert_text(record.get("location_start_line"))
    return f"Location: {path}:{line}" if line else f"Location: {path}"


def _severity_line(record: dict[str, Any]) -> str | None:
    severity = alert_text(record.get("security_severity_level")) or alert_text(record.get("rule_severity"))
    return f"Severity: {severity}" if severity else None


def github_code_scanning_alert_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    title = alert_text(record.get("rule_description")) or alert_text(record.get("rule_id"))
    message = alert_text(record.get("message_text"))
    full_description = alert_text(record.get("rule_full_description"), MAX_RULE_DESCRIPTION_CHARS)
    tool = alert_text(record.get("tool_name"))
    output = build_github_alert_output(
        team_id=team_id,
        record=record,
        source_product=SOURCE_PRODUCT,
        title=title,
        details=(
            message if message != title else None,
            _location_line(record),
            _severity_line(record),
            f"Tool: {tool}" if tool else None,
            full_description if full_description not in (title, message) else None,
        ),
        extra_fields=CODE_SCANNING_EXTRA_FIELDS,
    )
    if output is not None:
        output.extra["location_start_line"] = alert_text(record.get("location_start_line"))
    return output


GITHUB_CODE_SCANNING_ALERTS_CONFIG = SignalSourceTableConfig(
    source_product=SOURCE_PRODUCT,
    source_type="scanner_finding",
    emitter=github_code_scanning_alert_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=CODE_SCANNING_FIELDS,
    where_clause="state = 'open'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
