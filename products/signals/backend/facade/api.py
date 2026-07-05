import dataclasses
from datetime import datetime, timedelta

from django.conf import settings

import pydantic
import structlog
import temporalio
import posthoganalytics

from posthog.event_usage import groups
from posthog.helpers.tiktoken_encoding import LLM_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.signals.backend.contracts import SIGNAL_VARIANT_LOOKUP, SignalRemediation
from products.signals.backend.models import SignalReport, SignalSourceConfig

logger = structlog.get_logger(__name__)

MAX_SIGNAL_DESCRIPTION_TOKENS = 8000
MAX_SIGNAL_REMEDIATION_TOKENS = 16000


def _token_count(text: str) -> int:
    return len(get_tiktoken_encoding_for_model(LLM_TOKEN_COUNT_PROXY_MODEL).encode(text))


def dismiss_report_from_slack(
    team_id: int, report_id: str, *, slack_user_id: str | None = None, user_id: int | None = None
) -> bool:
    """Facade entrypoint for the Slack 'Dismiss' button. See report_actions.suppress_report_from_slack."""
    from products.signals.backend.report_actions import (
        suppress_report_from_slack,  # noqa: PLC0415 — avoids importing model layer at facade import time
    )

    return suppress_report_from_slack(team_id, report_id, slack_user_id=slack_user_id, user_id=user_id)


def get_default_slack_notification_channel(team_id: int) -> str | None:
    """Team-default Slack channel for signal notifications, stored as "<channel_id>|#name"."""
    from products.signals.backend.models import (
        SignalTeamConfig,  # noqa: PLC0415 — avoids importing model layer at facade import time
    )

    config = SignalTeamConfig.objects.filter(team_id=team_id).only("default_slack_notification_channel").first()
    if config is None:
        return None
    value = (config.default_slack_notification_channel or "").strip()
    return value or None


def set_default_slack_notification_channel(team_id: int, value: str | None) -> None:
    """Idempotently set the team-default Slack channel for signal notifications."""
    from products.signals.backend.models import (
        SignalTeamConfig,  # noqa: PLC0415 — avoids importing model layer at facade import time
    )

    SignalTeamConfig.objects.update_or_create(
        team_id=team_id,
        defaults={"default_slack_notification_channel": value or None},
    )


# ---------------------------------------------------------------------------
# Slack onboarding: the signal sources offered in the inbox onboarding flow.
# One catalog drives the list, the toggles, and the "connected" checks.
# ---------------------------------------------------------------------------

_DEFAULT_SESSION_ANALYSIS_SAMPLE_RATE = 0.1


@dataclasses.dataclass(frozen=True)
class OnboardingSource:
    """A signal source offered as a checkbox in the Slack onboarding flow, with current state."""

    key: str
    label: str
    description: str
    enabled: bool


@dataclasses.dataclass(frozen=True)
class _SourceSpec:
    key: str
    label: str
    description: str
    # The SignalSourceConfig (source_product, source_type) rows ticking this source enables.
    pairs: tuple[tuple[str, str], ...]
    needs_ai_approval: bool = False


_SOURCE_CATALOG: tuple[_SourceSpec, ...] = (
    _SourceSpec(
        "error_tracking",
        "Error tracking",
        "new, reopened & spiking issues",
        (
            ("error_tracking", "issue_created"),
            ("error_tracking", "issue_reopened"),
            ("error_tracking", "issue_spiking"),
        ),
    ),
    _SourceSpec(
        "session_replay",
        "Session replay analysis",
        "problems real users hit",
        (("session_replay", "session_analysis_cluster"),),
        needs_ai_approval=True,
    ),
)
_SOURCE_BY_KEY: dict[str, _SourceSpec] = {spec.key: spec for spec in _SOURCE_CATALOG}


def _ai_data_processing_approved(team_id: int) -> bool:
    return bool(
        Team.objects.filter(id=team_id).values_list("organization__is_ai_data_processing_approved", flat=True).first()
    )


def has_enabled_source(team_id: int) -> bool:
    """True once the team has at least one enabled signal source — i.e. there's something to respond to."""
    return SignalSourceConfig.objects.filter(team_id=team_id, enabled=True).exists()


def onboarding_sources(team_id: int) -> list[OnboardingSource]:
    """The onboarding sources, in order, with current enabled state (for pre-checking the checkboxes)."""
    enabled_pairs = set(
        SignalSourceConfig.objects.filter(team_id=team_id, enabled=True).values_list("source_product", "source_type")
    )
    return [
        OnboardingSource(
            key=spec.key,
            label=spec.label,
            description=spec.description,
            enabled=any(pair in enabled_pairs for pair in spec.pairs),
        )
        for spec in _SOURCE_CATALOG
    ]


def set_sources(team_id: int, user_id: int | None, selected_keys: list[str]) -> list[str]:
    """Sync the team's onboarding sources to ``selected_keys`` (tick = enable, untick = disable;
    enabling a source sets up its SignalSourceConfig). Returns the labels of any that couldn't be
    enabled because AI data processing isn't approved (session replay analysis)."""
    selected = set(selected_keys)
    ai_approved = _ai_data_processing_approved(team_id)
    blocked: list[str] = []
    for spec in _SOURCE_CATALOG:
        want_on = spec.key in selected
        if want_on and spec.needs_ai_approval and not ai_approved:
            # Wanted but AI-gated: leave the source as-is. Disabling here would silently turn off a
            # previously-approved source when the full checkbox snapshot is re-submitted.
            blocked.append(spec.label)
            continue
        for source_product, source_type in spec.pairs:
            if want_on:
                defaults: dict = {"enabled": True, "created_by_id": user_id}
                if source_type == "session_analysis_cluster":
                    defaults["config"] = {"sample_rate": _DEFAULT_SESSION_ANALYSIS_SAMPLE_RATE}
                obj, created = SignalSourceConfig.objects.get_or_create(
                    team_id=team_id, source_product=source_product, source_type=source_type, defaults=defaults
                )
                if not created and not obj.enabled:
                    obj.enabled = True
                    obj.save(update_fields=["enabled", "updated_at"])
            else:
                SignalSourceConfig.objects.filter(
                    team_id=team_id, source_product=source_product, source_type=source_type, enabled=True
                ).update(enabled=False)
    return blocked


# ---------------------------------------------------------------------------
# Cross-product reads: recent inbox reports (consumed by Pulse briefs).
# ---------------------------------------------------------------------------

# The source products whose reports Pulse briefs may read as input. Scout findings and
# replay-vision scanner findings both qualify; `pulse` is excluded FOREVER — a consumer that
# also *emits* signals must never read its own emitted output back as input (anti-amplification).
_BRIEF_INPUT_SOURCE_PRODUCTS: list[str] = [
    SignalSourceConfig.SourceProduct.SIGNALS_SCOUT.value,
    SignalSourceConfig.SourceProduct.REPLAY_VISION.value,
]


@dataclasses.dataclass(frozen=True)
class SignalReportSummary:
    """Read-only snapshot of an inbox report, for cross-product consumers."""

    id: str
    title: str
    summary: str
    total_weight: float
    signal_count: int


def get_recent_reports(team_id: int, since: datetime, limit: int = 20) -> list[SignalReportSummary]:
    """Recent inbox-visible reports with authored content, newest first.

    Scoped to reports backed by scout or replay-vision signals (see
    ``_BRIEF_INPUT_SOURCE_PRODUCTS``) so a consumer that also *emits* signals (Pulse) can never
    read its own emitted output back as input. Hidden statuses mirror the inbox list surface.
    Report content is LLM-authored, so this returns [] when the organization has not approved
    AI data processing — mirroring emit_signal's gate.
    """
    from products.signals.backend.temporal.signal_queries import (
        fetch_report_ids_for_source_products,  # noqa: PLC0415 — keeps the temporal stack off the facade import path
    )

    team = Team.objects.filter(id=team_id).select_related("organization").first()
    if team is None or not team.organization.is_ai_data_processing_approved:
        return []
    source_report_ids = fetch_report_ids_for_source_products(team, _BRIEF_INPUT_SOURCE_PRODUCTS)
    if not source_report_ids:
        return []
    reports = (
        SignalReport.objects.filter(id__in=source_report_ids, team_id=team_id, created_at__gte=since)
        .exclude(status__in=SignalReport.INBOX_HIDDEN_STATUSES)
        .exclude(title__isnull=True)
        .exclude(title="")
        .exclude(summary__isnull=True)
        .exclude(summary="")
        .order_by("-created_at")[:limit]
    )
    return [
        SignalReportSummary(
            id=str(report.id),
            title=report.title or "",
            summary=report.summary or "",
            total_weight=report.total_weight,
            signal_count=report.signal_count,
        )
        for report in reports
    ]


# The signal channel's generic `extra` passthrough only forwards top-level *scalar* values,
# each truncated — never nested lists/dicts. Source `extra` payloads nest *uncurated*
# customer-derived content (pganalyze `references[].queryText` raw SQL, session-replay
# `event_history`, scout `evidence` summaries) that we don't want to forward wholesale; scalars
# are the cheap-to-query attribution we actually want (`scout_run_id`, `task_run_id`,
# `skill_name`, …). The cap bounds top-level strings that could still be large (e.g. an
# `error_message`). This governs only the opaque `extra` blob — it is NOT a blanket ban on
# report substance in telemetry. The report channel deliberately forwards specific, curated,
# scout-authored fields (title / summary) on its own lifecycle events, where the content *is*
# the product output rather than an arbitrary nested blob; see `scout_harness/tools/report.py`.
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
            `SignalRemediation` schema and capped at MAX_SIGNAL_REMEDIATION_TOKENS tokens
            (`human` + `agent` combined). When set, the signal is treated as actionable: the guidance
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

    description_tokens = _token_count(description)
    if description_tokens > MAX_SIGNAL_DESCRIPTION_TOKENS:
        raise ValueError(
            f"Signal description exceeds {MAX_SIGNAL_DESCRIPTION_TOKENS} tokens ({description_tokens} tokens). "
            f"Truncate the description before calling emit_signal."
        )

    if remediation is not None:
        remediation_tokens = _token_count(f"{remediation.human}\n{remediation.agent}")
        if remediation_tokens > MAX_SIGNAL_REMEDIATION_TOKENS:
            raise ValueError(
                f"Signal remediation exceeds {MAX_SIGNAL_REMEDIATION_TOKENS} tokens ({remediation_tokens} tokens). "
                f"Trim the remediation guidance before calling emit_signal."
            )

    # Validate the signal against the matching schema variant
    variant_model = SIGNAL_VARIANT_LOOKUP.get((source_product, source_type))
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
