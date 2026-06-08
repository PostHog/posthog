import enum
from datetime import timedelta
from typing import get_args

from django.conf import settings

import pydantic
import structlog
import temporalio
import posthoganalytics

from posthog.schema import SignalInput, SignalRemediation

from posthog.event_usage import groups
from posthog.helpers.tiktoken_encoding import LLM_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.signals.backend.models import SignalSourceConfig

logger = structlog.get_logger(__name__)

MAX_SIGNAL_DESCRIPTION_TOKENS = 8000


def dismiss_report_from_slack(team_id: int, report_id: str, *, slack_user_id: str | None = None) -> bool:
    """Facade entrypoint for the Slack 'Dismiss' button. See report_actions.suppress_report_from_slack."""
    from products.signals.backend.report_actions import (
        suppress_report_from_slack,  # noqa: PLC0415 — avoids importing model layer at facade import time
    )

    return suppress_report_from_slack(team_id, report_id, slack_user_id=slack_user_id)


def _get_field_values(field: pydantic.fields.FieldInfo) -> tuple[str, ...]:
    """Extract all possible values for a Pydantic field (Literal, StrEnum, or default)."""
    args = get_args(field.annotation)
    if args:
        return args
    if isinstance(field.annotation, type) and issubclass(field.annotation, enum.Enum):
        return tuple(m.value for m in field.annotation)
    if field.default is not pydantic.fields.PydanticUndefined:
        return (field.default,)
    return ()


# Build a lookup from (source_product, source_type) -> variant model class
# so we can validate signals without needing the synthetic discriminator tag.
_SIGNAL_VARIANT_LOOKUP: dict[tuple[str, str], type[pydantic.BaseModel]] = {}
for _variant_type in get_args(SignalInput.model_fields["root"].annotation):
    _product_field = _variant_type.model_fields.get("source_product")
    _type_field = _variant_type.model_fields.get("source_type")
    if _product_field is None or _type_field is None:
        continue
    for _product in _get_field_values(_product_field):
        for _source_type in _get_field_values(_type_field):
            _SIGNAL_VARIANT_LOOKUP[(_product, _source_type)] = _variant_type


# Telemetry only forwards top-level *scalar* `extra` values, each truncated — never nested
# lists/dicts. Source `extra` payloads nest customer-derived content (pganalyze
# `references[].queryText` raw SQL, session-replay `event_history`, scout `evidence`
# summaries) that must not leak into product analytics; scalars are the cheap-to-query
# attribution we actually want (`scout_run_id`, `task_run_id`, `skill_name`, …). The cap
# bounds top-level strings that could still be large (e.g. an `error_message`).
_MAX_TELEMETRY_STR_LEN = 256


def _telemetry_props_from_extra(extra: dict | None) -> dict:
    if not extra:
        return {}
    props: dict = {}
    for key, value in extra.items():
        if isinstance(value, str):
            props[key] = value[:_MAX_TELEMETRY_STR_LEN]
        elif isinstance(value, (bool, int, float)):
            props[key] = value
    return props


async def emit_signal(
    team: Team,
    source_product: str,
    source_type: str,
    source_id: str,
    description: str,
    weight: float = 0.5,
    extra: dict | None = None,
    remediation: SignalRemediation | None = None,
) -> None:
    """
    Emit a signal for grouping and potential report generation, fire-and-forget.

    Active path:
        emit_signal() -> SignalEmitterWorkflow -> BufferSignalsWorkflow -> TeamSignalGroupingV2Workflow

    Args:
        team: The team object
        source_product: Product emitting the signal (e.g., "experiments", "web_analytics")
        source_type: Type of signal (e.g., "significance_reached", "traffic_anomaly")
        source_id: Unique identifier within the source (e.g., experiment UUID)
        description: Human-readable description that will be embedded
        weight: Importance/confidence of signal (0.0-1.0). Weight of 1.0 triggers summary.
        extra: Optional product-specific metadata. Its top-level scalar values (truncated) are
            flattened onto the `signal_emission_started` and `signal_emitted` analytics events
            alongside the core `source_*` keys (which win on conflict) — see
            `_telemetry_props_from_extra` — so per-source attribution (e.g. the scout harness's
            `scout_run_id` / `skill_name`) is queryable downstream without a schema change.
            Nested lists/dicts are never forwarded.
        remediation: Optional fix guidance (separate from extra), validated against the
            `SignalRemediation` schema. When set, the signal is treated as actionable: the guidance
            is surfaced to the research agent as authoritative direction, which it follows instead of
            investigating from scratch. Not required by any existing source.

    Example:
        await emit_signal(
            team=team,
            source_product="github",
            source_type="issue",
            source_id="posthog/posthog#12345",
            description="GitHub Issue #12345: Button doesn't work on Safari\nLabels: bug\n...",
            weight=0.8,
            extra={"html_url": "https://github.com/posthog/posthog/issues/12345", "number": 12345, ...},
        )
    """
    # Deferred: the temporal package imports the facade back (reingestion -> emit_signal), so
    # importing these workflows at module scope forms a circular import and drags the whole
    # temporal stack onto the Django startup path. Resolved lazily at call time instead.
    from products.signals.backend.temporal.buffer import BufferSignalsWorkflow  # noqa: PLC0415
    from products.signals.backend.temporal.emitter import SignalEmitterInput, SignalEmitterWorkflow  # noqa: PLC0415
    from products.signals.backend.temporal.types import BufferSignalsInput, EmitSignalInputs  # noqa: PLC0415

    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        return

    is_enabled = await database_sync_to_async(SignalSourceConfig.is_source_enabled, thread_sensitive=False)(
        team.id, source_product, source_type
    )
    if not is_enabled:
        return

    token_count = len(get_tiktoken_encoding_for_model(LLM_TOKEN_COUNT_PROXY_MODEL).encode(description))
    if token_count > MAX_SIGNAL_DESCRIPTION_TOKENS:
        raise ValueError(
            f"Signal description exceeds {MAX_SIGNAL_DESCRIPTION_TOKENS} tokens ({token_count} tokens). "
            f"Truncate the description before calling emit_signal."
        )

    # Validate the signal against the matching schema variant
    variant_model = _SIGNAL_VARIANT_LOOKUP.get((source_product, source_type))
    if variant_model is None:
        raise pydantic.ValidationError.from_exception_data(
            title="SignalInput",
            line_errors=[
                {
                    "type": "value_error",
                    "loc": ("source_product", "source_type"),
                    "input": {"source_product": source_product, "source_type": source_type},
                    "ctx": {"error": ValueError(f"Unknown signal type: {source_product}/{source_type}")},
                }
            ],
        )
    # Carry the remediation as a plain dict from here on (like `extra`) so it survives the
    # Temporal/S3 JSON round-trip; `model_validate` below re-checks it against the variant's
    # declared `remediation: SignalRemediation | None` field.
    remediation_dict = remediation.model_dump(mode="json", exclude_none=True) if remediation is not None else None
    payload_to_validate: dict = {
        "source_product": source_product,
        "source_type": source_type,
        "source_id": source_id,
        "description": description,
        "weight": weight,
        "extra": extra or {},
        "remediation": remediation_dict,
    }
    variant_model.model_validate(payload_to_validate)

    # Fire a "started" marker so direct callers (error tracking, AI observability evals, etc.)
    # that don't go through the data-source pipeline still have a top-of-funnel event. The
    # gap to `signal_emitted` surfaces Temporal/dispatch failures.
    try:
        posthoganalytics.capture(
            event="signal_emission_started",
            distinct_id=str(team.uuid),
            properties={
                **_telemetry_props_from_extra(extra),
                "source_product": source_product,
                "source_type": source_type,
                "source_id": source_id,
            },
            groups=groups(organization, team),
        )
    except Exception:
        # Swallow the exception, to avoid breaking the flow over failed analytics event
        logger.exception(
            "Failed to capture signal_emission_started event",
            source_product=source_product,
            source_type=source_type,
            source_id=source_id,
        )

    client = await async_connect()

    signal_input = EmitSignalInputs(
        team_id=team.id,
        source_product=source_product,
        source_type=source_type,
        source_id=source_id,
        description=description,
        weight=weight,
        extra=extra or {},
        remediation=remediation_dict,
    )

    # Ensure the buffer workflow is running (idempotent)
    try:
        await client.start_workflow(
            BufferSignalsWorkflow.run,
            BufferSignalsInput(team_id=team.id),
            id=BufferSignalsWorkflow.workflow_id_for(team.id),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            run_timeout=timedelta(hours=1),
        )
    except temporalio.exceptions.WorkflowAlreadyStartedError:
        pass

    # Fire-and-forget: the emitter workflow will submit the signal to the buffer
    # via update, blocking if the buffer is full (backpressure).
    await client.start_workflow(
        SignalEmitterWorkflow.run,
        SignalEmitterInput(team_id=team.id, signal=signal_input),
        id=SignalEmitterWorkflow.workflow_id_for(team.id),
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        run_timeout=timedelta(minutes=10),
    )

    # Fire the analytics event only after the signal is definitively queued so
    # Temporal/connection failures don't inflate the "signals emitted" metric.
    try:
        posthoganalytics.capture(
            event="signal_emitted",
            distinct_id=str(team.uuid),
            properties={
                **_telemetry_props_from_extra(extra),
                "source_product": source_product,
                "source_type": source_type,
                "source_id": source_id,
            },
            groups=groups(organization, team),
        )
    except Exception:
        # Swallow the exception, to avoid breaking the flow over failed analytics event
        logger.exception(
            "Failed to capture signal_emitted event",
            source_product=source_product,
            source_type=source_type,
            source_id=source_id,
        )
