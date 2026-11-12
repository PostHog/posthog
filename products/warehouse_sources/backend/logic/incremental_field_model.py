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
from typing import TYPE_CHECKING

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
PROMPT_VERSION = 1
# Both endpoints block a person's screen, so _ask_all gives every request together this long.
TIMEOUT_SECONDS = 3.0
MIN_CONFIDENCE = 0.6
MAX_REQUESTS = 4
CACHE_TTL_SECONDS = 24 * 60 * 60
# Keyed per team: one team's table names must never answer for another team.
CACHE_KEY_PREFIX = "warehouse_incremental_field_model"
# Gateway requests per team. Renamed tables miss the cache, so the cache alone does not bound the calls.
TEAM_BUDGET = Budget(burst=12, per_hour=60)
TEAM_BUDGET_KEY_PREFIX = "warehouse_incremental_field_model_rate"

MODEL_PICK_NOTE = "Picked by AI from the table and column names."

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


def _recommend(schemas: Sequence[SourceSchema], team: "Team") -> None:
    pending = [schema for schema in schemas if _is_open(schema)]
    if not pending or not _model_allowed(team):
        return

    keys = {index: _cache_key(team.pk, schema) for index, schema in enumerate(pending)}
    cached = _cache_get_many(list(keys.values()))
    picks = {index: cached[key] for index, key in keys.items() if cached.get(key)}
    uncached = [index for index, key in keys.items() if key not in cached][: MAX_REQUESTS * GATEWAY_MAX_QUESTIONS]
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
    # Agreeing with the rules adds nothing. Marking it would also make append skip a column that may
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
