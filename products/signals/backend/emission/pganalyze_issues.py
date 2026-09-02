import re
import json
from typing import Any

from structlog import get_logger

from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
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
- A finding whose every cited statement is a database monitoring or platform query. Such a query reads Postgres system catalogs (`pg_catalog`, `pg_stat_*` views) or cloud provider functions (`rds_*()`). Nobody can index, rewrite, or tune a statement the platform issues.

The finding may end with a record_metadata block. `cited_queries` holds the SQL the finding cites, so judge those statements, not the query fingerprint or the call count. A monitoring statement stays NOT_ACTIONABLE however slow it is. A finding that also cites a statement the product issues is ACTIONABLE.

When in doubt, classify as ACTIONABLE — pganalyze findings are usually worth a look. Only mark NOT_ACTIONABLE if the finding clearly has no engineering follow-up.

<finding>
{description}
</finding>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""


REQUIRED_FIELDS = ("id", "description")

PASSTHROUGH_FIELDS = (
    "severity",
    "references",
    "database_id",
    "server_human_id",
    "server_name",
    "synced_at",
)

# `cited_queries` is derived from `references` rather than selected, so it is on `extra` only.
EXTRA_FIELDS = (*PASSTHROUGH_FIELDS, "cited_queries")

# The gate has to recognize what a statement reads, not review the whole plan. Both caps stay well
# inside the pipeline's record metadata budget, so the cited SQL cannot crowd out the rest of `extra`.
MAX_CITED_QUERIES = 3
MAX_CITED_QUERY_CHARS = 400

# Relations a statement reads, taken from its FROM and JOIN clauses.
_RELATION_PATTERN = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w.$]*)", re.IGNORECASE)

# Postgres reserves the `pg_` prefix for system objects, and AWS RDS reserves `rds_` for platform
# functions, so no PostHog code owns a relation with either prefix. `information_schema` holds
# catalog views whose names carry no such prefix.
_MONITORING_PREFIXES = ("pg_", "rds_")
_MONITORING_SCHEMAS = ("information_schema",)


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


def _cited_queries(references: list[dict[str, Any]]) -> list[str]:
    queries: list[str] = []
    for reference in references:
        query_text = reference.get("queryText") if isinstance(reference, dict) else None
        if isinstance(query_text, str) and query_text.strip():
            queries.append(query_text.strip()[:MAX_CITED_QUERY_CHARS])
        if len(queries) == MAX_CITED_QUERIES:
            break
    return queries


def _is_monitoring_relation(relation: str) -> bool:
    schema, _, name = relation.rpartition(".")
    if schema.lower() in _MONITORING_SCHEMAS:
        return True
    return name.lower().startswith(_MONITORING_PREFIXES)


def _reads_only_monitoring_relations(query_text: str) -> bool:
    relations = _RELATION_PATTERN.findall(query_text)
    return bool(relations) and all(_is_monitoring_relation(relation) for relation in relations)


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
    cited_queries = _cited_queries(references)
    # The prompt states this rule too, and must keep stating it. This check reads only FROM and JOIN
    # clauses, so the LLM stays the backstop for the forms it misses.
    if cited_queries and all(_reads_only_monitoring_relations(query) for query in cited_queries):
        logger.info(
            "Ignoring pganalyze issue that cites only database monitoring statements",
            source_id=issue_id,
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None

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
        extra=_build_extra(record, references, cited_queries),
    )


def _build_extra(record: dict[str, Any], references: list[dict[str, Any]], cited_queries: list[str]) -> dict[str, Any]:
    extra = {k: v for k, v in record.items() if k in PASSTHROUGH_FIELDS}
    extra["references"] = references
    # Omitted when the finding cites no SQL, so the gate prompt stays as it was for every non-query
    # finding, such as an index, vacuum, or log finding.
    if cited_queries:
        extra["cited_queries"] = cited_queries
    return extra


PGANALYZE_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="pganalyze",
    source_type="issue",
    emitter=pganalyze_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="synced_at",
    partition_field_is_datetime_string=True,
    fields=REQUIRED_FIELDS + PASSTHROUGH_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,  # 24 hours
    actionability_prompt=PGANALYZE_ACTIONABILITY_PROMPT,
    actionability_context_fields=("cited_queries",),
    summarization_prompt=PGANALYZE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
