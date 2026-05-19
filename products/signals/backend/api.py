import enum
from datetime import timedelta
from typing import get_args

from django.conf import settings

import pydantic
import tiktoken
import structlog
import temporalio
import posthoganalytics

from posthog.schema import SignalInput

from posthog.event_usage import groups
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.temporal.buffer import BufferSignalsWorkflow
from products.signals.backend.temporal.emitter import SignalEmitterInput, SignalEmitterWorkflow
from products.signals.backend.temporal.types import BufferSignalsInput, EmitSignalInputs

logger = structlog.get_logger(__name__)

MAX_SIGNAL_DESCRIPTION_TOKENS = 8000
_tiktoken_encoding = tiktoken.get_encoding("cl100k_base")


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


async def emit_signal(
    team: Team,
    source_product: str,
    source_type: str,
    source_id: str,
    description: str,
    weight: float = 0.5,
    extra: dict | None = None,
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
        extra: Optional product-specific metadata

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

    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        return

    is_enabled = await database_sync_to_async(SignalSourceConfig.is_source_enabled, thread_sensitive=False)(
        team.id, source_product, source_type
    )
    if not is_enabled:
        return

    token_count = len(_tiktoken_encoding.encode(description))
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
    variant_model.model_validate(
        {
            "source_product": source_product,
            "source_type": source_type,
            "source_id": source_id,
            "description": description,
            "weight": weight,
            "extra": extra or {},
        }
    )

    # Fire a "started" marker so direct callers (error tracking, LLM analytics evals, etc.)
    # that don't go through the data-source pipeline still have a top-of-funnel event. The
    # gap to `signal_emitted` surfaces Temporal/dispatch failures.
    try:
        posthoganalytics.capture(
            event="signal_emission_started",
            distinct_id=str(team.uuid),
            properties={
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
