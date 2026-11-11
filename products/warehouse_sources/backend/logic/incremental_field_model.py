"""Ask the decision model which incremental field to recommend when the column names leave it open.

`rank_incremental_fields` settles a table that has a column which changes on update. A table without
one (only `id` and `created_at`, a name such as `event_ts`, or names in another language) gets a guess
from the name rules. For those tables the decision model reads the table and column names, never row
values, and picks the column most likely to change on every write. A failed, refused or unsure answer
keeps the rule-based order.
"""

import json
import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from django.core.cache import cache

import structlog
from asgiref.sync import async_to_sync

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
    GATEWAY_MAX_QUESTIONS,
    GatewaySystemOneClient,
    build_system_one_client,
    system_one_configured,
)
from posthog.ph_client import feature_enabled_or_false
from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume

from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema, tracks_updates
from products.warehouse_sources.backend.types import IncrementalField

if TYPE_CHECKING:
    from posthog.models.team import Team

logger = structlog.get_logger(__name__)

FEATURE_FLAG = "warehouse-incremental-field-model"
AI_PRODUCT = "warehouse_sources"
MODEL = DEFAULT_DECISION_MODEL
PROMPT_VERSION = 1
# Both endpoints block a person's screen, so _ask_all gives every request together this long.
TIMEOUT_SECONDS = 3.0
MIN_CONFIDENCE = 0.6
MAX_REQUESTS = 4
CACHE_TTL_SECONDS = 24 * 60 * 60
PENDING_TTL_SECONDS = 10 * 60
# Keyed per team: one team's table names must never answer for another team.
CACHE_KEY_PREFIX = "warehouse_incremental_field_model"
# Gateway requests per team. Renamed tables miss the cache, so the cache alone does not bound the calls.
TEAM_BUDGET = Budget(burst=12, per_hour=60)
TEAM_BUDGET_KEY_PREFIX = "warehouse_incremental_field_model_rate"

MODEL_PICK_NOTE = "Picked by AI from the table and column names."
# Key in the schema's sync_type_config that holds the stored model pick for the sync settings form.
SUGGESTION_KEY = "incremental_field_suggestion"

_INSTRUCTIONS = (
    "state.tables.{table_id} is a database table and its columns that can be the cursor of an incremental sync. "
    "An incremental sync reads only the rows whose cursor value is greater than the last value it read. "
    "Pick the column whose value changes every time a row is inserted or updated, so that edited rows sync again. "
    "When two columns are equally likely, pick the indexed one that is never empty."
)


def recommend_incremental_fields(schemas: Sequence[SourceSchema], *, team: "Team") -> None:
    """Move the model's confident pick to the front of each open table's `incremental_fields`."""
    try:
        _recommend(schemas, team)
    except Exception as error:
        # The rule-based order is a complete answer, so a failure here must not fail the endpoint.
        capture_exception(error, {"team_id": team.pk})


def recommend_for_candidates(
    tables: Sequence[tuple[str, list[IncrementalField]]], *, team: "Team"
) -> dict[str, list[IncrementalField]]:
    """The reordered candidates of each table where the model made a pick, keyed by table name.

    For callers that already hold the ranked candidates, such as the source wizard after discovery,
    so the model call needs no second discovery.
    """
    schemas = [
        SourceSchema(name=name, supports_incremental=True, supports_append=True, incremental_fields=list(fields))
        for name, fields in tables
    ]
    recommend_incremental_fields(schemas, team=team)
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
    key = _candidates_key(schema)
    stored = (sync_type_config or {}).get(SUGGESTION_KEY)
    stored_field = (
        stored["field"]
        if isinstance(stored, dict) and stored.get("candidates") == key and isinstance(stored.get("field"), str)
        else None
    )
    # Checked before a stored pick too, so turning the flag off also withdraws stored picks.
    if (stored_field is None and not _is_open(schema)) or not _model_allowed(team):
        return
    if stored_field is not None:
        _apply_pick(schema, stored_field)
        return
    queued_key = f"{CACHE_KEY_PREFIX}:queued:{team.pk}:{schema_id}:{key}"
    if not _cache_add(queued_key, PENDING_TTL_SECONDS):
        return
    # Deferred import: the task module imports this one.
    from products.warehouse_sources.backend.tasks.tasks import compute_incremental_field_suggestion  # noqa: PLC0415

    try:
        # No publish retries: the form waits on this call, and the next open can try again.
        compute_incremental_field_suggestion.apply_async(
            kwargs={
                "team_id": team.pk,
                "schema_id": schema_id,
                "table": schema.name,
                "fields": [dict(f) for f in _candidates(schema)],
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
    picks = recommend_for_candidates([(table, fields)], team=team)
    if table not in picks:
        return
    update_sync_type_config_keys(
        schema_id,
        team.pk,
        updates={SUGGESTION_KEY: {"field": picks[table][0]["field"], "candidates": _candidates_key_for(fields)}},
    )


def _candidates_key(schema: SourceSchema) -> str:
    return _candidates_key_for(_candidates(schema))


def _candidates_key_for(fields: Sequence[IncrementalField]) -> str:
    shape = [
        [
            field["field"],
            str(field.get("field_type") or field["type"]),
            field.get("is_indexed", True),
            field.get("nullable", False),
        ]
        for field in fields
    ]
    return hashlib.sha256(json.dumps([MODEL, PROMPT_VERSION, shape]).encode()).hexdigest()


def _recommend(schemas: Sequence[SourceSchema], team: "Team") -> None:
    pending = [schema for schema in schemas if _is_open(schema)][: MAX_REQUESTS * GATEWAY_MAX_QUESTIONS]
    if not pending or not _model_allowed(team):
        return

    keys = {index: _cache_key(team.pk, schema) for index, schema in enumerate(pending)}
    cached = _cache_get_many(list(keys.values()))
    picks = {index: cached[key] for index, key in keys.items() if cached.get(key)}
    uncached = [index for index, key in keys.items() if key not in cached]
    batches = [
        uncached[start : start + GATEWAY_MAX_QUESTIONS] for start in range(0, len(uncached), GATEWAY_MAX_QUESTIONS)
    ]

    if batches and _within_team_budget(team.pk, len(batches)):
        client = build_system_one_client(
            model=MODEL,
            ai_product=AI_PRODUCT,
            distinct_id=team_distinct_id(team.pk),
            timeout=TIMEOUT_SECONDS,
            privacy_mode=True,
        )
        # No TypeSafe fallback is passed, so the client is always the gateway one.
        assert isinstance(client, GatewaySystemOneClient)
        answers = async_to_sync(_ask_all)(client, [[(i, pending[i]) for i in batch] for batch in batches])
        picks.update({index: field_name for index, field_name in answers.items() if field_name})
        _cache_set_many({keys[index]: field_name for index, field_name in answers.items()})

    changed = sum(_apply_pick(pending[index], field_name) for index, field_name in picks.items())
    logger.info(
        "incremental_field_model_applied",
        team_id=team.pk,
        open_tables=len(pending),
        asked=len(uncached),
        picked=len(picks),
        changed=changed,
    )


def _candidates(schema: SourceSchema) -> list[IncrementalField]:
    # Only ranked fields carry `recommended`, so a synthetic cursor such as xmin is never offered.
    return [field for field in schema.incremental_fields if "recommended" in field][:GATEWAY_MAX_CHOICE_OPTIONS]


def _is_open(schema: SourceSchema) -> bool:
    candidates = _candidates(schema)
    return len(candidates) >= 2 and not tracks_updates(candidates[0])


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


def _within_team_budget(team_id: int, requests: int) -> bool:
    decision = consume(f"{TEAM_BUDGET_KEY_PREFIX}:{team_id}", TEAM_BUDGET, cost=requests)
    match decision:
        case BucketUnavailable():
            # Fail open: one call is still bounded by MAX_REQUESTS.
            logger.warning("incremental_field_model_budget_unavailable", team_id=team_id)
            return True
        case BucketDecision(allowed=False):
            logger.info("incremental_field_model_budget_exhausted", team_id=team_id)
            return False
        case BucketDecision():
            return True


def _table_state(schema: SourceSchema) -> dict[str, JsonValue]:
    return {
        "table": schema.name,
        "columns": [
            {
                "option": f"c{position}",
                "name": field["field"],
                "type": str(field.get("field_type") or field["type"]),
                "indexed": field.get("is_indexed", True),
                "nullable": field.get("nullable", False),
            }
            for position, field in enumerate(_candidates(schema))
        ],
    }


async def _ask_all(client: GatewaySystemOneClient, batches: list[list[tuple[int, SourceSchema]]]) -> dict[int, str]:
    """Run every batch under one deadline. A request still open at the deadline is cancelled."""
    tasks = [asyncio.create_task(_ask(client, batch)) for batch in batches]
    done, late = await asyncio.wait(tasks, timeout=TIMEOUT_SECONDS)
    for task in late:
        task.cancel()
    if late:
        await asyncio.gather(*late, return_exceptions=True)
        logger.warning("incremental_field_model_deadline_reached", late_requests=len(late))
    answers: dict[int, str] = {}
    for task in done:
        # One failed request must not drop the answers of the others.
        if (error := task.exception()) is not None:
            capture_exception(error)
            continue
        answers.update(task.result() or {})
    return answers


async def _ask(client: GatewaySystemOneClient, tables: list[tuple[int, SourceSchema]]) -> Mapping[int, str] | None:
    """The confident pick per table index, or None when the request failed. An unsure table maps to ''."""
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
    try:
        result = await client.adecide(state=state, questions=questions)
    except (SystemOneRequestFailed, SystemOneNotConfigured) as error:
        logger.warning("incremental_field_model_failed", error_type=type(error).__name__)
        return None

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
    if chosen is None:
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
    return chosen is not fields[0]


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
