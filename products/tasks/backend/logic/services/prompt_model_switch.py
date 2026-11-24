"""The model or reasoning effort that a PostHog AI message asks its run to use, such as "use opus for this".

A new or resumed run reads it before the run exists, so any harness is open. A live run reads it
before the agent gets the follow-up, and stays on its harness, because the harness process is
fixed when the sandbox starts.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from django.core.cache import cache

import structlog

from posthog.models import Team, User

from products.tasks.backend.facade.contracts import RunModelSelection
from products.tasks.backend.feature_flags import get_model_access_error, prompt_model_switch_enabled
from products.tasks.backend.logic.model_override import (
    ModelOverride,
    ModelOverrideAttribution,
    classify_model_override,
    may_request_model_override,
)
from products.tasks.backend.logic.services.gateway_model_pin import (
    model_allowed_by_product_pin,
    pinned_run_allows_model,
)
from products.tasks.backend.logic.services.model_catalogue import (
    TASK_RUN_GATEWAY_PRODUCT,
    available_model_choices,
    filter_unsupported_effort,
    runtime_adapter_for,
)
from products.tasks.backend.logic.services.run_actor import get_actor_distinct_id

logger = structlog.get_logger(__name__)

# The task create and the run create of one new chat carry the same message. The answer is kept
# long enough for the second request to reuse it, rather than pay for a second classifier call.
_CACHE_TTL_SECONDS = 120
_NO_SWITCH = "none"
# A PostHog AI run mints its gateway token under this product, so a model outside its pin fails the run.
# The catalogue lists the wider PostHog Code set, and a new run has no stamped pin to check yet.
_GATEWAY_PRODUCT = "posthog_ai"


def _cache_key(team: Team, user: User, runtime_adapter: str | None, text: str) -> str:
    digest = hashlib.sha256(f"{team.id}:{user.id}:{runtime_adapter}:{text}".encode()).hexdigest()
    return f"tasks:prompt_model_switch:{digest}"


def _cached(key: str) -> ModelOverride | None | str:
    # The cache only saves a classifier call, so an unreachable cache must not fail the request.
    try:
        cached = cache.get(key)
    except Exception:
        logger.exception("prompt_model_switch_cache_read_failed")
        return None
    if cached == _NO_SWITCH:
        return _NO_SWITCH
    return ModelOverride(**cached) if isinstance(cached, dict) else None


def _remember(key: str, override: ModelOverride | None) -> None:
    value: Any = (
        _NO_SWITCH if override is None else {"model": override.model, "reasoning_effort": override.reasoning_effort}
    )
    try:
        cache.set(key, value, timeout=_CACHE_TTL_SECONDS)
    except Exception:
        logger.exception("prompt_model_switch_cache_write_failed")


def requested_model_switch(
    message: str,
    *,
    team: Team,
    user: User,
    runtime_adapter: str | None = None,
    run_state: Mapping[str, Any] | None = None,
) -> ModelOverride | None:
    """The switch a message asks for, or ``None``. ``runtime_adapter`` limits the answer to the models of one harness."""
    from products.posthog_ai.backend.turn_suggestions.transcript import (  # noqa: PLC0415 — keeps PostHog AI off the tasks import path
        strip_context_blocks,
    )

    from ee.hogai.utils.feature_flags import is_privacy_mode_enabled  # noqa: PLC0415

    # The composer puts page context in front of the person's text. The context is not an
    # instruction, and its untrusted part can hold any text, so the classifier never reads it.
    text = strip_context_blocks(message)
    if not text:
        return None
    catalogue = tuple(
        choice
        for choice in available_model_choices(TASK_RUN_GATEWAY_PRODUCT)
        if runtime_adapter in (None, choice.runtime_adapter)
    )
    # The classifier sends the person's text to a third-party AI service, so it needs the organization's
    # consent. The check comes before the cache, so a revoked consent also stops a cached answer.
    # The flag and model access checks are network calls, so the free word check goes first.
    if (
        not may_request_model_override(text, catalogue)
        or team.organization.is_ai_data_processing_approved is not True
        or not prompt_model_switch_enabled(team, user)
    ):
        return None

    key = _cache_key(team, user, runtime_adapter, text)
    cached = _cached(key)
    if cached == _NO_SWITCH:
        return None
    if isinstance(cached, ModelOverride):
        return cached

    distinct_id = get_actor_distinct_id(user)
    choices = tuple(
        choice
        for choice in catalogue
        if get_model_access_error(choice.model, distinct_id=distinct_id) is None
        and model_allowed_by_product_pin(_GATEWAY_PRODUCT, choice.model)
        and pinned_run_allows_model(dict(run_state) if run_state is not None else None, choice.model)
    )
    override = classify_model_override(
        text,
        choices,
        ModelOverrideAttribution(
            ai_product="posthog_ai",
            properties={"posthog_ai_feature": "model_override"},
            distinct_id=distinct_id,
            privacy_mode=is_privacy_mode_enabled(team),
        ),
    )
    _remember(key, override)
    return override


def with_prompt_model_switch(
    message: str, selection: RunModelSelection, *, team: Team, user: User
) -> RunModelSelection:
    """The selection a new run starts with when its first message asks for a model or an effort.

    The message wins over the picker, because it is the later instruction. The harness follows
    the model, so the permission mode is clamped to what the new harness offers.
    """
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keeps the sandbox config off the api import path
        clamp_initial_permission_mode,
    )

    override = requested_model_switch(message, team=team, user=user)
    if override is None:
        return selection
    if override.model:
        runtime_adapter = runtime_adapter_for(override.model)
        switched = replace(
            selection,
            runtime_adapter=runtime_adapter,
            model=override.model,
            reasoning_effort=filter_unsupported_effort(
                runtime_adapter, override.model, override.reasoning_effort or selection.reasoning_effort
            ),
            initial_permission_mode=clamp_initial_permission_mode(runtime_adapter, selection.initial_permission_mode)
            if selection.initial_permission_mode
            else None,
        )
    elif override.reasoning_effort:
        # The run rejects an effort its model lacks, which would stop the message from starting it.
        # An unpinned run launches on the stored default, so the check reads the model it resolves to.
        from products.tasks.backend.logic.services.ai_run_defaults import (  # noqa: PLC0415 — ai_run_defaults imports the tasks ORM
            resolve_ai_run_selection,
        )

        resolved = resolve_ai_run_selection(
            team.id, user.id, runtime_adapter=selection.runtime_adapter, model=selection.model
        )
        effort = filter_unsupported_effort(
            resolved.runtime_adapter or runtime_adapter_for(resolved.model), resolved.model, override.reasoning_effort
        )
        if not effort:
            return selection
        switched = replace(selection, reasoning_effort=effort)
    else:
        return selection
    logger.info("prompt_model_switch_applied", model=switched.model, reasoning_effort=switched.reasoning_effort)
    return switched
