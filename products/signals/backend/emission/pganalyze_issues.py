import json
from datetime import datetime
from typing import Any

from structlog import get_logger

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.emission.fetchers.data_warehouse import escape_table_name
from products.signals.backend.emission.fetchers.emission_ledger import already_emitted_source_ids
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

PGANALYZE_SUMMARIZATION_PROMPT = """Summarize this pganalyze database performance finding for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) capturing the core finding (e.g. "Missing index on users.email")
2. A concise summary capturing the database, the kind of issue (slow query, missing index, vacuum problem, log event, etc.), the affected query or relation if mentioned, and any suggested remediation

Strip raw query plans, large SQL excerpts, and per-row metrics — but keep specific table/index names, error messages, and the type of operation involved if they clarify the issue.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<finding>
{description}
</finding>
"""

PGANALYZE_ACTIONABILITY_PROMPT = """You are a database performance analyst. Given a pganalyze finding (an "issue" surfaced by a pganalyze check — covering missing indexes, slow queries, vacuum problems, schema changes, log events, etc.), determine if it represents something engineers could address with code, schema, or configuration changes.

A finding is ACTIONABLE if it describes:
- A missing or unused index recommendation
- A slow or regressed query that could be optimized, rewritten, or supported by an index
- A vacuum, autovacuum, or bloat problem with a clear remediation
- A schema or configuration issue (e.g. fillfactor, work_mem, shared_buffers) with concrete advice
- A replication, checkpoint, or WAL problem that engineers can address
- A log event, error, or deadlock that engineers can fix at the application or database layer
- A pganalyze check failure that points to specific tables, queries, or settings

A finding is NOT_ACTIONABLE if it is:
- Purely informational with no recommended action ("snapshot succeeded", "collector started")
- A transient or self-resolving condition with no remediation
- A duplicate of a higher-severity finding already represented elsewhere
- A noise check that fires on every snapshot regardless of severity

When in doubt, classify as ACTIONABLE — pganalyze findings are usually worth a look. Only mark NOT_ACTIONABLE if the finding clearly has no engineering follow-up.

<finding>
{description}
</finding>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""


REQUIRED_FIELDS = ("id", "description")

EXTRA_FIELDS = (
    "severity",
    "references",
    "database_id",
    "server_human_id",
    "server_name",
    "synced_at",
)

ISSUE_PAGE_SIZE = 1_000


def _parse_references(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw_refs = record.get("references")
    if raw_refs is None:
        return []
    if isinstance(raw_refs, str):
        try:
            parsed: Any = json.loads(raw_refs)
        except (json.JSONDecodeError, TypeError) as e:
            msg = f"pganalyze issue references field is not valid JSON: {raw_refs!r}"
            logger.exception(msg, record=record, signals_type="data-import-signals")
            raise ValueError(msg) from e
    else:
        parsed = raw_refs
    if not isinstance(parsed, list):
        msg = f"pganalyze issue references field is not a list: {parsed!r}"
        logger.error(msg, record=record, signals_type="data-import-signals")
        raise ValueError(msg)
    return parsed


def _first_reference_name(references: list[dict[str, Any]]) -> str | None:
    if not references:
        return None
    first = references[0] if isinstance(references[0], dict) else {}
    return first.get("name")


def pganalyze_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = record["id"]
        description = record["description"]
    except KeyError as e:
        msg = f"pganalyze issue record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not issue_id or not description:
        msg = f"pganalyze issue record has empty required field: id={issue_id!r}, description={description!r}"
        logger.error(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg)

    severity = record.get("severity") or "unknown"
    server_name = record.get("server_name") or record.get("server_human_id") or "unknown server"
    references = _parse_references(record)
    ref_name = _first_reference_name(references)

    title_parts = [f"[{severity}]", server_name]
    if ref_name:
        title_parts.append(f"— {ref_name}")
    signal_description = f"{' '.join(title_parts)}\n{description}"

    return SignalEmitterOutput(
        source_product="pganalyze",
        source_type="issue",
        source_id=str(issue_id),
        description=signal_description,
        weight=1.0,
        extra=_build_extra(record, references),
    )


def _build_extra(record: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    extra = {k: v for k, v in record.items() if k in EXTRA_FIELDS}
    extra["references"] = references
    return extra


def _fetch_issue_page(
    team: Team, config: SignalSourceTableConfig, context: dict[str, Any], after_id: str
) -> list[dict[str, Any]]:
    placeholders: dict[str, Any] = {"after_id": ast.Constant(value=after_id)}
    if context.get("last_synced_at") is not None:
        window = "parseDateTimeBestEffort(synced_at) > {last_synced_at}"
        placeholders["last_synced_at"] = ast.Constant(value=datetime.fromisoformat(context["last_synced_at"]))
    else:
        window = f"parseDateTimeBestEffort(synced_at) > now() - interval {config.first_sync_lookback_days} day"
    # Weekly warehouse partitions can retain older versions of the same issue.
    query = f"""
        SELECT {", ".join(config.fields)}
        FROM {escape_table_name(context["table_name"])}
        WHERE {window} AND id > {{after_id}}
        ORDER BY id ASC, parseDateTimeBestEffort(synced_at) DESC
        LIMIT 1 BY id
        LIMIT {ISSUE_PAGE_SIZE}
    """
    result = execute_hogql_query(
        query=parse_select(query, placeholders=placeholders),
        team=team,
        query_type="EmitSignalsNewRecords",
        bypass_warehouse_access_control=True,
    )
    if not result.results or not result.columns:
        return []
    return [dict(zip(result.columns, row)) for row in result.results]


def pganalyze_issue_record_fetcher(
    team: Team,
    config: SignalSourceTableConfig,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """pganalyze stamps open issues on every sync, so the time cursor alone cannot deduplicate them."""
    records: list[dict[str, Any]] = []
    after_id = ""
    while len(records) < config.max_records:
        rows = _fetch_issue_page(team, config, context, after_id)
        if not rows:
            break
        already_emitted = already_emitted_source_ids(team, config, [str(row["id"]) for row in rows])
        records.extend(row for row in rows if str(row["id"]) not in already_emitted)
        after_id = str(rows[-1]["id"])
        if len(rows) < ISSUE_PAGE_SIZE:
            break
    return records[: config.max_records]


PGANALYZE_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="pganalyze",
    source_type="issue",
    emitter=pganalyze_issue_emitter,
    record_fetcher=pganalyze_issue_record_fetcher,
    record_processed_outputs=True,
    # The fetcher reads only the rows of the latest sync, which are the issues that are open now.
    partition_field="synced_at",
    partition_field_is_datetime_string=True,
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,  # 24 hours
    actionability_prompt=PGANALYZE_ACTIONABILITY_PROMPT,
    summarization_prompt=PGANALYZE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
