import uuid
import dataclasses
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction

import pydantic
import structlog
import temporalio
import posthoganalytics
from temporalio.common import WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.helpers.tiktoken_encoding import LLM_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.signals.backend.contracts import DIRECT_STEERABLE_SOURCES, SIGNAL_VARIANT_LOOKUP, SignalRemediation
from products.signals.backend.enums import SIGNAL_SOURCE_PRODUCT_LABELS, SignalSourceProduct
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun, SignalSourceConfig
from products.signals.backend.signal_metadata import fetch_signal_stats_for_source_slice

# Re-exported for external products (tasks presentation catches it around facade create_task).
from products.signals.backend.task_run_artefacts import ReportTaskCapExceeded as ReportTaskCapExceeded

if TYPE_CHECKING:
    from products.tasks.backend.facade.repo_selection import RepoSelectionResult

logger = structlog.get_logger(__name__)

MAX_SIGNAL_DESCRIPTION_TOKENS = 8000
MAX_SIGNAL_REMEDIATION_TOKENS = 16000


@dataclasses.dataclass(frozen=True)
class SignalSourceTypesState:
    """configured = any bundle row exists; all_enabled = every type is currently enabled."""

    configured: bool
    all_enabled: bool


def signal_source_types_state(
    *, team_id: int, source_product: str, source_types: tuple[str, ...]
) -> SignalSourceTypesState:
    rows = list(
        SignalSourceConfig.objects.filter(
            team_id=team_id,
            source_product=source_product,
            source_type__in=source_types,
        ).values_list("source_type", "enabled")
    )
    enabled_types = {source_type for source_type, enabled in rows if enabled}
    return SignalSourceTypesState(configured=bool(rows), all_enabled=enabled_types == set(source_types))


def set_signal_source_types_enabled(
    *,
    team_id: int,
    source_product: str,
    source_types: tuple[str, ...],
    enabled: bool,
    created_by_id: int,
    config: dict | None = None,
) -> None:
    """Atomically update a product-owned bundle of signal-source types. Every enable refreshes
    ``created_by``. Provided ``config`` keys are merged into each row's stored config rather than
    replacing it, so re-enables can't wipe keys they don't manage (e.g. an operator's ``dry_run``)."""
    with transaction.atomic():
        Team.objects.select_for_update().only("id").get(id=team_id)
        if not enabled:
            SignalSourceConfig.objects.filter(
                team_id=team_id,
                source_product=source_product,
                source_type__in=source_types,
            ).update(enabled=False)
            return
        for source_type in source_types:
            row, _ = SignalSourceConfig.objects.update_or_create(
                team_id=team_id,
                source_product=source_product,
                source_type=source_type,
                defaults={"enabled": True, "created_by_id": created_by_id},
            )
            if config is not None:
                merged = {**row.config, **config} if isinstance(row.config, dict) else dict(config)
                if merged != row.config:
                    row.config = merged
                    row.save(update_fields=["config"])


def _token_count(text: str) -> int:
    return len(get_tiktoken_encoding_for_model(LLM_TOKEN_COUNT_PROXY_MODEL).encode(text))


def validate_signal_input(
    *,
    source_product: str,
    source_type: str,
    source_id: str,
    description: str,
    weight: float,
    extra: dict | None,
    remediation: SignalRemediation | None,
) -> dict | None:
    """The single emit-time schema check; emitters' tests call it directly so payloads can't drift
    from the contract unnoticed. Raises ``pydantic.ValidationError`` on an unknown type pair or
    mismatched payload; returns the JSON-safe remediation dict ``emit_signal`` forwards."""
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
    remediation_dict = remediation.model_dump(mode="json", exclude_none=True) if remediation is not None else None
    variant_model.model_validate(
        {
            "source_product": source_product,
            "source_type": source_type,
            "source_id": source_id,
            "description": description,
            "weight": weight,
            "extra": extra or {},
            "remediation": remediation_dict,
        }
    )
    return remediation_dict


def dismiss_report_from_slack(
    team_id: int, report_id: str, *, slack_user_id: str | None = None, user_id: int | None = None
) -> bool:
    """Facade entrypoint for the Slack 'Dismiss' button. See report_actions.suppress_report_from_slack."""
    from products.signals.backend.report_actions import (
        suppress_report_from_slack,  # noqa: PLC0415 — avoids importing model layer at facade import time
    )

    return suppress_report_from_slack(team_id, report_id, slack_user_id=slack_user_id, user_id=user_id)


def persisted_repo_selection(report_id: str) -> "RepoSelectionResult | None":
    """Facade entrypoint for a report's latest repo selection. See select_repo.persisted_repo_selection."""
    from products.signals.backend.report_generation.select_repo import (
        persisted_repo_selection as persisted_repo_selection_impl,  # noqa: PLC0415 — avoids importing model layer at facade import time
    )

    return persisted_repo_selection_impl(report_id)


def autostart_base_branch_for_repository(team_id: int, repository: str | None) -> str | None:
    """Team's configured base branch for ``repository``, for callers outside the signals product."""
    if not repository:
        return None

    from products.signals.backend.models import (
        SignalTeamConfig,  # noqa: PLC0415 — avoids importing model layer at facade import time
    )

    config = SignalTeamConfig.objects.filter(team_id=team_id).only("autostart_base_branches").first()
    return config.base_branch_for(repository) if config is not None else None


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


@dataclasses.dataclass(frozen=True)
class OnboardingSource:
    """A signal source shown in the Slack onboarding flow, with current state."""

    key: str
    label: str
    description: str
    enabled: bool
    # False for a source that authorizes itself elsewhere: onboarding reports it instead of
    # offering a checkbox that would have nothing to write.
    togglable: bool = True


def _has_emitting_replay_scanner(team_id: int) -> bool:
    from products.replay_vision.backend.facade.api import (
        has_signal_emitting_scanner,  # noqa: PLC0415 — keeps the Replay Vision stack off this import path
    )

    return has_signal_emitting_scanner(team_id)


@dataclasses.dataclass(frozen=True)
class _SourceSpec:
    key: str
    label: str
    description: str
    # The SignalSourceConfig (source_product, source_type) rows ticking this source enables.
    # Empty when the source authorizes itself elsewhere, which is also what makes it untickable.
    pairs: tuple[tuple[str, str], ...] = ()
    # Reads the on/off state of a source that has no config row to read it from.
    enabled_check: Callable[[int], bool] | None = None


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
        "replay_vision",
        "Replay vision",
        "bugs and UX problems scanners find in recordings",
        enabled_check=_has_emitting_replay_scanner,
    ),
)
_SOURCE_BY_KEY: dict[str, _SourceSpec] = {spec.key: spec for spec in _SOURCE_CATALOG}


# The two statuses a reader still has something to do about, and the only two that stamp
# `first_visible_at`. An allowlist rather than a denylist, so a status added later is not silently
# offered to a first-time user.
_OFFERABLE_STATUSES = (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)


@frozen
class InboxReportSummary:
    """One report, named well enough for an agent to offer it by id."""

    report_id: str
    title: str


@frozen
class WaitingReports:
    """What a team has waiting in its inbox: how many, and the newest few that can be named.

    `offerable` is shorter than `count` whenever more are waiting than the caller asked for, or one
    has no title yet. That is expected, not a mismatch — see `waiting_reports`.
    """

    count: int
    offerable: tuple[InboxReportSummary, ...]


_REPORT_TITLE_LIMIT = 120


def waiting_reports(team_id: int, limit: int = 3) -> WaitingReports:
    """What is waiting in the team's inbox, newest named first.

    One eligibility rule for both halves, because they drifted apart when there were two:
    `first_visible_at` is stamped once on the first transition into ready or pending_input and never
    cleared, so the status filter is the only thing keeping a resolved, archived or re-running report
    from reading as one that is waiting.

    The two halves then differ on titles, deliberately. `count` is what the inbox will show them, and
    the inbox renders a titleless report from its summary, so it counts. `offerable` has to name a
    report in a sentence, so a titleless one is skipped rather than offered as a blank row.
    """
    waiting = SignalReport.objects.filter(
        team_id=team_id, first_visible_at__isnull=False, status__in=_OFFERABLE_STATUSES
    )
    newest_named = (
        waiting.exclude(title__isnull=True)
        .exclude(title="")
        .order_by("-first_visible_at")
        .values_list("id", "title")[:limit]
    )
    return WaitingReports(
        count=waiting.count(),
        offerable=tuple(
            InboxReportSummary(report_id=str(report_id), title=" ".join((title or "").split())[:_REPORT_TITLE_LIMIT])
            for report_id, title in newest_named
        ),
    )


def has_enabled_source(team_id: int) -> bool:
    """True once the team has at least one enabled signal source — i.e. there's something to respond to.

    Replay Vision is checked separately because it has no config row to find: each scanner's own
    `emits_signals` flag authorizes it (see `SignalSourceConfig.is_source_enabled`)."""
    if (
        SignalSourceConfig.objects.filter(team_id=team_id, enabled=True)
        # Retired: rows outlive the feature until the cleanup migration runs, and counting one marks
        # onboarding complete on a source that emits nothing.
        .exclude(source_product="session_replay", source_type="session_analysis_cluster")
        .exists()
    ):
        return True
    return _has_emitting_replay_scanner(team_id)


def team_ids_with_source_product_enabled(source_product: str) -> list[int]:
    """Team ids with at least one enabled source of ``source_product`` — the enrolment list a
    product's own scheduled emitter fans out over (e.g. engineering_analytics' CI-signals
    coordinator). Per-``source_type`` and org AI-approval gating still happens in ``emit_signal``;
    this is the cheap pre-filter so a sweep skips teams that never turned the product on."""
    return list(
        SignalSourceConfig.objects.filter(source_product=source_product, enabled=True)
        .values_list("team_id", flat=True)
        .distinct()
    )


def is_signal_source_enabled(team_id: int, source_product: str, source_type: str) -> bool:
    """Whether ``emit_signal`` will accept this ``(source_product, source_type)`` for the team, or
    silently drop it. A scheduled emitter that pre-checks this can skip a disabled type instead of
    recording a phantom emission in its own dedupe ledger — ``emit_signal`` returns silently, not by
    raising, so the caller can't otherwise tell an accepted emit from a dropped one."""
    return SignalSourceConfig.is_source_enabled(team_id, source_product, source_type)


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
            enabled=(
                spec.enabled_check(team_id) if spec.enabled_check else any(pair in enabled_pairs for pair in spec.pairs)
            ),
            togglable=bool(spec.pairs),
        )
        for spec in _SOURCE_CATALOG
    ]


def set_sources(team_id: int, user_id: int | None, selected_keys: list[str]) -> None:
    """Sync the team's onboarding sources to ``selected_keys`` (tick = enable, untick = disable;
    enabling a source sets up its SignalSourceConfig)."""
    selected = set(selected_keys)
    for spec in _SOURCE_CATALOG:
        if not spec.pairs:
            # Authorized elsewhere (Replay Vision, per scanner), so onboarding never offered it as a
            # checkbox and has nothing to write here.
            continue
        want_on = spec.key in selected
        for source_product, source_type in spec.pairs:
            if want_on:
                defaults: dict = {"enabled": True, "created_by_id": user_id}
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


# Each source carries two names: the label, which is the product it comes from, and the watch, which
# is the problem it catches. Onboarding copy needs the second one, because "error tracking" tells a
# first-time reader nothing about what turning it on did for them.
_ONBOARDING_NATIVE_SOURCES: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        SignalSourceProduct.ERROR_TRACKING,
        ("issue_created", "issue_reopened", "issue_spiking"),
        "error tracking",
        "errors",
    ),
    (SignalSourceProduct.HEALTH_CHECKS, ("health_issue",), "health checks", "failing health checks"),
    (SignalSourceProduct.CONVERSATIONS, ("ticket",), "support tickets", "support tickets"),
    (SignalSourceProduct.LLM_ANALYTICS, ("evaluation_report",), "AI observability", "AI evals"),
    (SignalSourceProduct.ANALYTICS, ("anomaly_investigation",), "product analytics", "metric swings"),
)


_ONBOARDING_LABELS: dict[str, str] = {product: label for product, _, label, _watch in _ONBOARDING_NATIVE_SOURCES}


@dataclasses.dataclass(frozen=True)
class OnboardingSources:
    labels: tuple[str, ...]
    watches: tuple[str, ...]
    newly_enabled: bool


def _active_source_labels(team_id: int) -> tuple[str, ...]:
    products = (
        SignalSourceConfig.objects.filter(team_id=team_id, enabled=True)
        .values_list("source_product", flat=True)
        .distinct()
    )
    labels = {
        _ONBOARDING_LABELS.get(product) or SIGNAL_SOURCE_PRODUCT_LABELS.get(SignalSourceProduct(product), product)
        for product in products
    }
    return tuple(sorted(labels))


def enable_onboarding_signal_sources(team_id: int, user_id: int) -> OnboardingSources:
    known = set(SignalSourceConfig.objects.filter(team_id=team_id).values_list("source_product", "source_type"))
    created: list[str] = []
    watches: list[str] = []
    for source_product, source_types, label, watch in _ONBOARDING_NATIVE_SOURCES:
        missing = tuple(t for t in source_types if (source_product, t) not in known)
        if not missing:
            continue
        try:
            set_signal_source_types_enabled(
                team_id=team_id,
                source_product=source_product,
                source_types=missing,
                enabled=True,
                created_by_id=user_id,
            )
        except Exception:
            logger.exception("onboarding_signal_source_enable_failed", team_id=team_id, source_product=source_product)
            continue
        created.append(label)
        watches.append(watch)
    if created:
        return OnboardingSources(labels=tuple(created), watches=tuple(watches), newly_enabled=True)
    return OnboardingSources(labels=_active_source_labels(team_id), watches=(), newly_enabled=False)


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

# Keys that name a person rather than attribute a signal. A source may carry one on `extra` because
# triage needs it (a GitHub issue's `author_login` separates a maintainer's report from a stranger's),
# but no lifecycle event needs the identity, so the scalar passthrough drops it.
_TELEMETRY_EXCLUDED_EXTRA_KEYS = frozenset({"author_login"})


def _telemetry_props_from_extra(extra: dict | None) -> dict:
    if not extra:
        return {}
    props: dict = {}
    for key, value in extra.items():
        if key in _TELEMETRY_EXCLUDED_EXTRA_KEYS:
            continue
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
    idempotency_key: str | None = None,
) -> None:
    """
    Emit a signal for grouping and potential report generation, fire-and-forget.

    Active path:
        emit_signal() -> SignalEmitterWorkflow -> BufferSignalsWorkflow -> TeamSignalGroupingV2Workflow

    A source in `DIRECT_STEERABLE_SOURCES` is checked against the team's steering first and dropped
    when the team's rules say to skip it (see `emission/direct_gate.py`). A team that wrote no
    steering is unaffected. Sources that reach here through the batch pipeline already ran their own
    steered gate, so they stay out of that set and are never judged twice.

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
        idempotency_key: Optional stable key for callers that may retry. Repeated calls with
            the same key, source product, and source type start at most one emitter workflow.

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
    if idempotency_key is not None and not idempotency_key.strip():
        raise ValueError("idempotency_key must not be empty")

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

    remediation_dict = validate_signal_input(
        source_product=source_product,
        source_type=source_type,
        source_id=source_id,
        description=description,
        weight=weight,
        extra=extra,
        remediation=remediation,
    )

    # Fire a "started" marker so direct callers (error tracking, AI observability evals, etc.)
    # that don't go through the data-source pipeline still have a top-of-funnel event. The gap to
    # `signal_emitted` surfaces Temporal/dispatch failures, once the steering gate below is
    # subtracted: started - signal_data_source_filtered - emitted = failures.
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

    # Below the started event on purpose: a filtered signal then has a top-of-funnel event to be
    # counted against, so a steering drop reads apart from a dispatch failure rather than as one.
    if (source_product, source_type) in DIRECT_STEERABLE_SOURCES:
        # Deferred: the emission package imports this facade back, and its __init__ registers every
        # emitter, which must stay off the import path of Celery workers and management commands.
        from products.signals.backend.emission.direct_gate import steering_filters_signal  # noqa: PLC0415

        if await steering_filters_signal(
            team=team,
            organization=organization,
            source_product=source_product,
            source_type=source_type,
            source_id=source_id,
            description=description,
            weight=weight,
            extra=extra or {},
        ):
            return

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
    emitter_idempotency_key = (
        f"{source_product}:{source_type}:{idempotency_key}" if idempotency_key is not None else None
    )
    try:
        await client.start_workflow(
            SignalEmitterWorkflow.run,
            SignalEmitterInput(team_id=team.id, signal=signal_input),
            id=SignalEmitterWorkflow.workflow_id_for(team.id, emitter_idempotency_key),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            run_timeout=timedelta(minutes=10),
            id_reuse_policy=(
                WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                if emitter_idempotency_key is not None
                else WorkflowIDReusePolicy.ALLOW_DUPLICATE
            ),
        )
    except temporalio.exceptions.WorkflowAlreadyStartedError:
        if emitter_idempotency_key is None:
            raise
        return

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


def forward_report_discussion_note(
    *,
    team: Team,
    report_id: str | None,
    relationship: str | None,
    text: str,
    user_id: int | None,
    scoped_team_ids: Sequence[int] | None,
    api_scopes: Sequence[str] | None,
) -> str | None:
    """Forward an inbox "Discuss" question to the report's scout as a steering note.

    Called by the tasks presentation layer once a discussion task exists, with the calling
    credential's reach (`scoped_team_ids`, `api_scopes`) read off the request there — the note write
    is gated on authorization the task creation itself doesn't require. Only a `discussion`
    relationship forwards, so an implementation or research kickoff never leaves a note. Best-effort:
    returns the note id, or None when nothing was forwarded.
    """
    from products.signals.backend.artefact_schemas import (  # noqa: PLC0415 — keeps the notes stack off this module's import path
        TASK_RUN_TYPE_DISCUSSION,
    )
    from products.signals.backend.discussion_notes import forward_discussion_note  # noqa: PLC0415 — same

    if relationship != TASK_RUN_TYPE_DISCUSSION or not report_id:
        return None

    return forward_discussion_note(
        team=team,
        report_id=report_id,
        text=text,
        user_id=user_id,
        scoped_team_ids=scoped_team_ids,
        api_scopes=api_scopes,
    )


@dataclasses.dataclass(frozen=True)
class SignalSourceSliceOutcomes:
    """What one source slice's signals led to: reports they were grouped into and the PRs off those."""

    signal_count: int
    report_count: int
    pr_count: int
    merged_pr_count: int


def get_outcomes_for_signal_source_slice(
    *, team: Team, source_product: str, source_type: str, extra_equals: dict[str, str]
) -> SignalSourceSliceOutcomes:
    """Aggregate downstream outcomes for signals of `(source_product, source_type)` narrowed by
    equality on `extra` keys (e.g. Replay Vision's `scanner_id`).

    Reports are counted only if the row still exists for this team and is not soft-deleted; a
    report usually aggregates signals from several sources, so these are contributions, not sole
    causes. PR counts come from the same implementation-PR resolution the inbox uses (latest
    PR-bearing task run per report), deduplicated by URL since reports can share a task's PR.
    """
    from products.signals.backend.implementation_pr import (  # noqa: PLC0415 — keeps the tasks facade off this module's import path
        fetch_implementation_pr_state_for_reports,
    )

    stats = fetch_signal_stats_for_source_slice(
        team, source_product=source_product, source_type=source_type, extra_equals=extra_equals
    )
    # CH metadata is not authoritative — keep only report ids that parse and still exist for this team.
    candidate_ids = []
    for report_id in stats.report_ids:
        try:
            candidate_ids.append(uuid.UUID(report_id))
        except ValueError:
            continue
    report_ids = [
        str(rid)
        for rid in SignalReport.objects.filter(team=team, id__in=candidate_ids)
        .exclude(status=SignalReport.Status.DELETED)
        .values_list("id", flat=True)
    ]
    prs = fetch_implementation_pr_state_for_reports(report_ids)
    pr_urls = {pr.url for pr in prs.values()}
    merged_pr_urls = {pr.url for pr in prs.values() if pr.merged}
    return SignalSourceSliceOutcomes(
        signal_count=stats.signal_count,
        report_count=len(report_ids),
        pr_count=len(pr_urls),
        merged_pr_count=len(merged_pr_urls),
    )


@frozen
class ScoutCreated:
    """What a scout creation produced. `created` is False when a scout of that name already existed
    and the supplied config was applied to it instead."""

    skill: Any
    config: Any
    created: bool


def create_scout_for_source(
    *,
    team: "Team",
    user: Any,
    name: str,
    description: str,
    body: str,
    files: list[Any],
    config_options: dict[str, Any],
    request: Any,
    serializer_context: dict[str, Any],
    source_product: str,
    source_id: str,
) -> "ScoutCreated":
    """Create a scout owned by one of another product's objects, recording `(source_product,
    source_id)` on its config.

    The caller must already have checked that the requesting user may act on the object it names —
    the pair is not settable through the public scout API precisely because Signals cannot make that
    check for an object it knows nothing about. Imported here rather than defined here because the
    creation flow lives with the private helpers it shares with the scout create endpoint.
    """
    # Imported inside the call to keep the view module (and the whole API surface it imports) off the
    # facade's import path, which Celery workers and management commands also load.
    from products.signals.backend.scout_harness.views import (  # noqa: PLC0415 — keeps the API surface off the import path
        create_scout_for_source as _create,
    )

    outcome = _create(
        team=team,
        user=user,
        name=name,
        description=description,
        body=body,
        files=files,
        config_options=config_options,
        request=request,
        serializer_context=serializer_context,
        source_product=source_product,
        source_id=source_id,
    )
    return ScoutCreated(skill=outcome.skill, config=outcome.config, created=outcome.created)


@frozen
class ScoutReport:
    """A report a scout filed, with the run that filed it. `filed_at` is that run's start, which is
    what a reader means by when the report landed; the report row's own timestamps move on later edits."""

    report_id: str
    skill_name: str
    filed_at: datetime
    title: str
    summary: str
    # Charts the scout attached, in the stored `{chart_id, title, query, caption?, size?}` shape. The
    # summary places one inline with a `[label](chart:<chart_id>)` link.
    charts: list[dict[str, Any]]


def scout_reports_for_source(
    team_id: int,
    source_product: str,
    source_id: str,
    *,
    report_id: str | None = None,
    limit: int = 50,
) -> list[ScoutReport]:
    """Reports filed by the scouts another product stood up for one of its objects, newest first.

    `(source_product, source_id)` is recorded on the config at creation and is not user-editable, so
    this doubles as the ownership check: a report filed by a scout belonging to something else is not
    returned, which lets a caller answer "is this report mine to show?" without reading scout tables.
    """
    skill_names = list(
        SignalScoutConfig.objects.for_team(team_id)
        .filter(source_product=source_product, source_id=source_id)
        .values_list("skill_name", flat=True)
    )
    if not skill_names:
        return []

    # Authorship only, never `edited_report_ids`: `edit_report` resolves its target by team alone, so
    # a scout can edit a report it did not write. Treating an edit as ownership would expose any
    # report one of these scouts happened to touch to a caller who only has access to this source.
    runs = (
        SignalScoutRun.objects.for_team(team_id)
        .filter(skill_name__in=skill_names)
        # A run that filed nothing cannot contribute a report, and a scout that runs often but files
        # rarely would otherwise stream its whole history through here to return a short list. With
        # empty runs excluded, `limit` rows is always enough, so Postgres stops rather than Python.
        .exclude(emitted_report_ids=[])
        .exclude(emitted_report_ids__isnull=True)
        .order_by("-created_at")
    )
    if report_id is not None:
        # Index-backed by `signal_scout_run_emitted_idx`, so a single report read does not walk the
        # team's run history.
        # `@>` served by `signal_scout_run_emitted_idx`. Exactly one run emits a given report, so
        # one row is all there is to find.
        runs = runs.filter(emitted_report_ids__contains=[report_id])[:1]

    filed: dict[str, tuple[str, datetime]] = {}
    if report_id is None:
        runs = runs[:limit]
    for skill_name, created_at, emitted_ids in runs.values_list(
        "skill_name", "created_at", "emitted_report_ids"
    ).iterator():
        for candidate in emitted_ids or []:
            # A report is emitted by exactly one run, so this run is the one that filed it.
            if candidate not in filed:
                filed[candidate] = (skill_name, created_at)
        if report_id is not None:
            if report_id in filed:
                break
        elif len(filed) >= limit:
            break

    wanted = [report_id] if report_id is not None else list(filed)[:limit]
    # A deleted or suppressed report is one the platform decided not to show; surfacing it here
    # would route around that decision.
    rows = SignalReport.objects.filter(team_id=team_id, id__in=[w for w in wanted if w in filed]).exclude(
        status__in=[SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED]
    )
    by_id = {str(row.id): row for row in rows}
    reports: list[ScoutReport] = []
    for candidate in wanted:
        row = by_id.get(candidate)
        if row is None:
            continue
        skill_name, created_at = filed[candidate]
        reports.append(
            ScoutReport(
                report_id=candidate,
                skill_name=skill_name,
                filed_at=created_at,
                title=row.title or "",
                summary=row.summary or "",
                charts=row.charts or [],
            )
        )
    return reports
