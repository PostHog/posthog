"""Ask the decision model which incremental field to recommend when the column names leave it open.

`rank_incremental_fields` settles a table that has a column which changes on update. A table without
one (only `id` and `created_at`, a name such as `event_ts`, or names in another language) gets a guess
from the name rules. For those tables the decision model reads the table and column names, never row
values, and picks the column most likely to change on every write. A failed, refused or unsure answer
keeps the rule-based order.
"""

import json
import time
import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from django.core.cache import cache

import structlog
from asgiref.sync import async_to_sync

from posthog.event_usage import report_team_action
from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.system_one import (
    ChoiceAnswer,
    ChoiceQuestion,
    JsonValue,
    Question,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
)
from posthog.llm.system_one_client import (
    GATEWAY_MAX_CHOICE_OPTIONS,
    GatewaySystemOneClient,
    build_system_one_client,
    system_one_configured,
)
from posthog.ph_client import feature_enabled_or_false
from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume

from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys
from products.warehouse_sources.backend.tasks.tasks import compute_incremental_field_suggestion
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    name_is_silent,
    tracks_updates,
)
from products.warehouse_sources.backend.types import IncrementalField

if TYPE_CHECKING:
    from posthog.models.team import Team

logger = structlog.get_logger(__name__)

FEATURE_FLAG = "warehouse-incremental-field-model"
AI_PRODUCT = "warehouse_sources"
MODEL = DEFAULT_DECISION_MODEL
# One model call per request. A call stays small enough to answer well inside this.
TIMEOUT_SECONDS = 3.0
MIN_CONFIDENCE = 0.6
# One call asks about at most this many tables and candidate columns in total, so the prompt stays
# small. A table with more candidates than the column limit is asked about on its own.
MAX_TABLES_PER_CALL = 8
MAX_COLUMNS_PER_CALL = 32
# Callers send their own names, so the model reads at most this much of each one. Picks map back by
# position, so a cut name still resolves to its full column.
MAX_NAME_CHARS = 256
CACHE_TTL_SECONDS = 24 * 60 * 60
QUEUED_TTL_SECONDS = 10 * 60
# Keyed per team: one team's table names must never answer for another team.
CACHE_KEY_PREFIX = "warehouse_incremental_field_model"
# Tables asked about per team. Renamed tables miss the cache, so the cache alone does not bound the calls.
TEAM_BUDGET = Budget(burst=200, per_hour=1000)
TEAM_BUDGET_KEY_PREFIX = "warehouse_incremental_field_model_rate"

MODEL_PICK_NOTE = "Picked by AI from the table and column names."
# Callers named in the usage event.
WIZARD_PATH = "wizard"
SYNC_FORM_PATH = "sync_form"
# Key in the schema's sync_type_config that holds the stored model pick for the sync settings form.
SUGGESTION_KEY = "incremental_field_suggestion"

_INSTRUCTIONS = (
    "state.tables.{table_id} is a database table and its columns that can be the cursor of an incremental sync. "
    "An incremental sync reads only the rows whose cursor value is greater than the last value it read. "
    "Pick the column whose value only grows across the whole table and grows again when a row is updated, "
    "so that new and edited rows sync again. A per-row counter such as a version number does not qualify, "
    "since an edited row can still hold a smaller value than another row. "
    "When two columns are equally likely, pick the indexed one that is never empty."
)
# Keys every cached and stored answer, so editing the instructions retires the old answers.
PROMPT_VERSION = hashlib.sha256(_INSTRUCTIONS.encode()).hexdigest()[:12]


def recommend_incremental_fields(schemas: Sequence[SourceSchema], *, team: "Team", path: str) -> None:
    """Move the model's confident pick to the front of each open table's `incremental_fields`.

    Makes at most one model call. `path` names the caller in the usage event.
    """
    try:
        _recommend(schemas, team, path)
    except Exception as error:
        # The rule-based order is a complete answer, so a failure here must not fail the endpoint.
        capture_exception(error, {"team_id": team.pk})


def recommend_for_candidates(
    tables: Sequence[tuple[str, list[IncrementalField]]], *, team: "Team", path: str
) -> dict[str, list[IncrementalField]]:
    """The reordered candidates of each table where the model made a pick, keyed by table name.

    For callers that already hold the ranked candidates, such as the source wizard after discovery,
    so the model call needs no second discovery.
    """
    # A caller's `picked_by_model` is dropped, so an earlier answer sent back cannot pass as a new pick.
    schemas = [
        SourceSchema(
            name=name,
            supports_incremental=True,
            supports_append=True,
            incremental_fields=[_without_model_pick(field) for field in fields],
        )
        for name, fields in tables
    ]
    recommend_incremental_fields(schemas, team=team, path=path)
    return {
        schema.name: schema.incremental_fields
        for schema in schemas
        if schema.incremental_fields and schema.incremental_fields[0].get("picked_by_model")
    }


def apply_stored_suggestion(
    schema: SourceSchema, sync_type_config: Mapping[str, Any] | None, *, team: "Team", schema_id: str
) -> None:
    """Move a stored model pick to the front, or queue one to be computed and stored.

    The sync settings form opens one table at a time, so asking the model on each open would make
    the person wait for it. The first open shows the rule-based order and queues the question; later
    opens read the stored answer. A stored pick only counts while the table has the same candidates.
    """
    try:
        _apply_stored_suggestion(schema, sync_type_config, team=team, schema_id=schema_id)
    except Exception as error:
        # The rule-based order is a complete answer, so a failure here must not fail the endpoint.
        capture_exception(error, {"team_id": team.pk})


def _apply_stored_suggestion(
    schema: SourceSchema, sync_type_config: Mapping[str, Any] | None, *, team: "Team", schema_id: str
) -> None:
    # Checked before a stored pick too, so turning the flag off also withdraws stored picks.
    if not _is_open(schema) or not _model_allowed(team):
        return
    key = _candidates_key(schema)
    stored = (sync_type_config or {}).get(SUGGESTION_KEY)
    if isinstance(stored, dict) and stored.get("candidates") == key and isinstance(stored.get("field"), str):
        _apply_pick(schema, stored["field"])
        return
    # Taken before a pick reorders them, so the task asks about and keys the same columns.
    candidates = _candidates(schema)
    # The wizard or an earlier task may have asked about these columns already.
    answer_key = _cache_key(team.pk, schema)
    cached = _cache_get_many([answer_key]).get(answer_key)
    if cached in ("", candidates[0]["field"]):
        # The model was unsure or agreed with the rules, so there is nothing to store.
        return
    if cached:
        _apply_pick(schema, cached)
    _queue_suggestion(schema.name, candidates, team=team, schema_id=schema_id, candidates_key=key)


def _queue_suggestion(
    table: str, candidates: list[IncrementalField], *, team: "Team", schema_id: str, candidates_key: str
) -> None:
    queued_key = f"{CACHE_KEY_PREFIX}:queued:{team.pk}:{schema_id}:{candidates_key}"
    if not _cache_add(queued_key, QUEUED_TTL_SECONDS):
        return
    try:
        # No publish retries: the form waits on this call, and the next open can try again.
        compute_incremental_field_suggestion.apply_async(
            kwargs={
                "team_id": team.pk,
                "schema_id": schema_id,
                "table": table,
                "fields": [dict(field) for field in candidates],
            },
            retry=False,
        )
    except Exception as error:
        capture_exception(error, {"team_id": team.pk})
        _cache_delete(queued_key)


def store_incremental_field_suggestion(
    team: "Team", schema_id: str, table: str, fields: list[IncrementalField]
) -> None:
    """Ask the model for one table and store a confident pick on the schema."""
    picks = recommend_for_candidates([(table, fields)], team=team, path=SYNC_FORM_PATH)
    if table not in picks:
        return
    asked = SourceSchema(name=table, supports_incremental=True, supports_append=True, incremental_fields=fields)
    update_sync_type_config_keys(
        schema_id,
        team.pk,
        updates={SUGGESTION_KEY: {"field": picks[table][0]["field"], "candidates": _candidates_key(asked)}},
    )


def _candidates_key(schema: SourceSchema) -> str:
    # The columns as the model reads them, so a change to what it reads or how sure it must be
    # withdraws stored picks. The table name is left out, so a renamed table keeps its pick.
    columns = _table_state(schema)["columns"]
    return hashlib.sha256(json.dumps([MODEL, PROMPT_VERSION, MIN_CONFIDENCE, columns]).encode()).hexdigest()


def _without_model_pick(field: IncrementalField) -> IncrementalField:
    cleaned: IncrementalField = {**field}
    cleaned.pop("picked_by_model", None)
    if "notes" in cleaned:
        cleaned["notes"] = [note for note in cleaned["notes"] if note != MODEL_PICK_NOTE]
    return cleaned


def fits_one_call(column_counts: Sequence[int]) -> bool:
    """Whether tables with these candidate counts go in one model call.

    A call holds up to MAX_TABLES_PER_CALL tables and MAX_COLUMNS_PER_CALL columns in total, and a
    table over the column limit always goes alone.
    """
    if len(column_counts) <= 1:
        return True
    return len(column_counts) <= MAX_TABLES_PER_CALL and sum(column_counts) <= MAX_COLUMNS_PER_CALL


def _recommend(schemas: Sequence[SourceSchema], team: "Team", path: str) -> None:
    pending = [schema for schema in schemas if _is_open(schema)]
    if not pending or not _model_allowed(team):
        return

    keys = {index: _cache_key(team.pk, schema) for index, schema in enumerate(pending)}
    cached = _cache_get_many(list(keys.values()))
    picks = {index: cached[key] for index, key in keys.items() if cached.get(key)}
    uncached = _first_call([index for index, key in keys.items() if key not in cached], pending)

    asked: list[int] = []
    outcome = "cached"
    if uncached and not _within_team_budget(team.pk, len(uncached)):
        outcome = "budget_exhausted"
    elif uncached:
        asked = uncached
        answers, outcome = _ask_once(team, [(index, pending[index]) for index in asked])
        picks.update({index: field_name for index, field_name in answers.items() if field_name})
        _cache_set_many({keys[index]: field_name for index, field_name in answers.items()})

    changed = sum(_apply_pick(pending[index], field_name) for index, field_name in picks.items())
    summary = {
        "path": path,
        "outcome": outcome,
        "open_tables": len(pending),
        "asked_tables": len(asked),
        "picked_tables": len(picks),
        "changed_defaults": changed,
    }
    logger.info("incremental_field_model_applied", team_id=team.pk, **summary)
    report_team_action(team, "incremental field model answered", summary)


def _first_call(indexes: list[int], schemas: Sequence[SourceSchema]) -> list[int]:
    """The leading tables that fit one model call. Callers send one call's worth, so this rarely cuts."""
    counts: list[int] = []
    for index in indexes:
        if not fits_one_call([*counts, len(_candidates(schemas[index]))]):
            break
        counts.append(len(_candidates(schemas[index])))
    return indexes[: len(counts)]


def _candidates(schema: SourceSchema) -> list[IncrementalField]:
    # Only ranked fields carry `recommended`, so a synthetic cursor such as xmin is never offered.
    return [field for field in schema.incremental_fields if "recommended" in field][:GATEWAY_MAX_CHOICE_OPTIONS]


def _is_open(schema: SourceSchema) -> bool:
    candidates = _candidates(schema)
    # With every name saying "created" or "updated", the rules already know the answer.
    return len(candidates) >= 2 and not tracks_updates(candidates[0]) and any(map(name_is_silent, candidates))


def _model_allowed(team: "Team") -> bool:
    if team.organization.is_ai_data_processing_approved is not True or not system_one_configured():
        return False
    organization_id = str(team.organization_id)
    return feature_enabled_or_false(
        FEATURE_FLAG,
        organization_id,
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        send_feature_flag_events=False,
    )


def _within_team_budget(team_id: int, tables: int) -> bool:
    decision = consume(f"{TEAM_BUDGET_KEY_PREFIX}:{team_id}", TEAM_BUDGET, cost=tables)
    match decision:
        case BucketUnavailable():
            # Fail open: one call is still bounded by MAX_TABLES_PER_CALL.
            logger.warning("incremental_field_model_budget_unavailable", team_id=team_id)
            return True
        case BucketDecision(allowed=False):
            logger.info("incremental_field_model_budget_exhausted", team_id=team_id)
            return False
        case BucketDecision():
            return True


def _table_state(schema: SourceSchema) -> dict[str, JsonValue]:
    return {
        "table": schema.name[:MAX_NAME_CHARS],
        "columns": [
            {
                "option": f"c{position}",
                "name": field["field"][:MAX_NAME_CHARS],
                "type": str(field.get("field_type") or field["type"]),
                "indexed": field.get("is_indexed", True),
                "nullable": field.get("nullable", False),
            }
            for position, field in enumerate(_candidates(schema))
        ],
    }


def _ask_once(team: "Team", tables: list[tuple[int, SourceSchema]]) -> tuple[Mapping[int, str], str]:
    """One model call under the deadline. Returns the picks and the call outcome."""
    client = build_system_one_client(
        model=MODEL,
        ai_product=AI_PRODUCT,
        distinct_id=team_distinct_id(team.pk),
        timeout=TIMEOUT_SECONDS,
        privacy_mode=True,
    )
    # No TypeSafe fallback is passed, so the client is always the gateway one.
    assert isinstance(client, GatewaySystemOneClient)
    columns = sum(len(_candidates(schema)) for _, schema in tables)
    started = time.monotonic()
    answers, outcome, status_code = async_to_sync(_ask_with_deadline)(client, tables)
    logger.info(
        "incremental_field_model_call",
        team_id=team.pk,
        tables=len(tables),
        columns=columns,
        latency_ms=round((time.monotonic() - started) * 1000),
        outcome=outcome,
        status_code=status_code,
    )
    return answers, outcome


async def _ask_with_deadline(
    client: GatewaySystemOneClient, tables: list[tuple[int, SourceSchema]]
) -> tuple[Mapping[int, str], str, int | None]:
    try:
        return await asyncio.wait_for(_ask(client, tables), timeout=TIMEOUT_SECONDS), "ok", None
    except TimeoutError:
        return {}, "timeout", None
    except SystemOneRequestFailed as error:
        return {}, "failed", error.status_code
    except SystemOneNotConfigured:
        return {}, "failed", None
    except Exception as error:
        capture_exception(error)
        return {}, "error", None


async def _ask(client: GatewaySystemOneClient, tables: list[tuple[int, SourceSchema]]) -> Mapping[int, str]:
    """The confident pick per table index. An unsure table maps to ''."""
    state: dict[str, JsonValue] = {"tables": {f"t{index}": _table_state(schema) for index, schema in tables}}
    questions: dict[str, Question] = {
        f"t{index}": ChoiceQuestion(
            instructions=_INSTRUCTIONS.format(table_id=f"t{index}"),
            criteria={
                f"c{position}": f"The column with option c{position} in state.tables.t{index}.columns"
                for position in range(len(_candidates(schema)))
            },
        )
        for index, schema in tables
    }
    result = await client.adecide(state=state, questions=questions)
    picks: dict[int, str] = {}
    for index, schema in tables:
        answer = result.answers.get(f"t{index}")
        candidates = _candidates(schema)
        picks[index] = ""
        if isinstance(answer, ChoiceAnswer) and answer.confidence >= MIN_CONFIDENCE:
            position = answer.choice.removeprefix("c")
            if position.isdigit() and int(position) < len(candidates):
                picks[index] = candidates[int(position)]["field"]
    return picks


def _apply_pick(schema: SourceSchema, field_name: str) -> bool:
    fields = schema.incremental_fields
    chosen = next((field for field in fields if field["field"] == field_name and "recommended" in field), None)
    # Agreeing with the rules adds nothing, and marking it would make append skip a column that may
    # never change, such as `created_at`.
    if chosen is None or chosen is fields[0]:
        return False
    rest: list[IncrementalField] = [
        {**field, "recommended": False} if "recommended" in field else field for field in fields if field is not chosen
    ]
    schema.incremental_fields = [
        {
            **chosen,
            "recommended": True,
            "picked_by_model": True,
            "notes": [MODEL_PICK_NOTE, *chosen.get("notes", [])],
        },
        *rest,
    ]
    return True


def _cache_key(team_id: int, schema: SourceSchema) -> str:
    digest = hashlib.sha256(
        json.dumps([MODEL, PROMPT_VERSION, MIN_CONFIDENCE, _table_state(schema)], sort_keys=True).encode()
    ).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{team_id}:{digest}"


def _cache_add(key: str, timeout: int) -> bool:
    """Set `key` only if it is absent. False when it was present or the cache failed."""
    try:
        return bool(cache.add(key, 1, timeout))
    except Exception:
        logger.warning("incremental_field_model_cache_add_failed", exc_info=True)
        return False


def _cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:
        logger.warning("incremental_field_model_cache_delete_failed", exc_info=True)


def _cache_get_many(keys: list[str]) -> dict[str, str]:
    try:
        found = cache.get_many(keys)
    except Exception:
        logger.warning("incremental_field_model_cache_read_failed", exc_info=True)
        return {}
    return {key: value for key, value in found.items() if isinstance(value, str)}


def _cache_set_many(values: dict[str, str]) -> None:
    if not values:
        return
    try:
        cache.set_many(values, CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("incremental_field_model_cache_write_failed", exc_info=True)
