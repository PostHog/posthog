"""Signal emitter for azure_devops `work_item_revisions` (record kind: issue).

The table holds one row per revision. Only revision 1 is read, so each work item emits once, when
it is created. Title, description and metadata live in the `fields` JSON, keyed by reference names
such as `System.Title`. Descriptions are HTML.
"""

import re
import html
from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

AZURE_DEVOPS_FIELDS = (
    "id",
    "changed_date",
    "JSONExtractString(fields, 'System.Title') AS title",
    "JSONExtractString(fields, 'System.Description') AS description",
    "JSONExtractString(fields, 'System.State') AS state",
    "JSONExtractString(fields, 'System.WorkItemType') AS work_item_type",
    "JSONExtractRaw(fields, 'Microsoft.VSTS.Common.Priority') AS priority",
)

MAX_BODY_CHARS = 4000
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_BREAK_RE = re.compile(r"</?(?:p|div|br|li|ul|ol|h[1-6]|tr)\b[^>]*>", re.IGNORECASE)


def html_to_text(raw: Any) -> str:
    if not isinstance(raw, str) or not raw:
        return ""
    text = _TAG_RE.sub("", _BLOCK_BREAK_RE.sub("\n", raw))
    lines = (re.sub(r"\s+", " ", html.unescape(line)).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)[:MAX_BODY_CHARS]


def azure_devops_work_item_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        work_item_id = record["id"]
        title = record["title"]
    except KeyError as e:
        msg = f"Azure DevOps work item record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not work_item_id or not title:
        logger.info(
            "Ignoring Azure DevOps work item with empty id or title",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    body = html_to_text(record.get("description"))
    changed_date = record.get("changed_date")
    priority = str(record.get("priority") or "").strip('"')
    return SignalEmitterOutput(
        source_product="azure_devops",
        source_type="issue",
        source_id=str(work_item_id),
        description=f"{title}\n{body}" if body else str(title),
        weight=1.0,
        extra={
            "work_item_type": record.get("work_item_type") or None,
            "state": record.get("state") or None,
            "priority": priority or None,
            "created_at": None if changed_date is None else str(changed_date),
        },
    )


AZURE_DEVOPS_CONFIG = SignalSourceTableConfig(
    source_product="azure_devops",
    source_type="issue",
    emitter=azure_devops_work_item_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="changed_date",
    partition_field_is_datetime_string=True,
    fields=AZURE_DEVOPS_FIELDS,
    where_clause="toString(rev) = '1'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
