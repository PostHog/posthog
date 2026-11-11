"""One pass of an agent over an entity: what is set up before the agent runs, and what is settled after.

A pass has three steps. The workflow in `temporal/agent_run.py` drives them, and this module holds
what each step writes:

1. `begin_pass` marks the row `running` once the entity is loaded and screened.
2. The agent runs as a scout run. `store_agent_run_output` keeps the record the agent returns.
3. `complete_pass` writes the links, the result, and the next pass if a request waited.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.agent_run_links import attached_reports
from products.signals.backend.agent_run_types import AgentEntity, AgentRunOutcome, AgentRunResult
from products.signals.backend.constants import SUPPORT_TICKET_SCOUT
from products.signals.backend.emission.steering import steering_from_config
from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.models import (
    SignalAgentRun,
    SignalReportEntityLink,
    SignalScoutConfig,
    SignalScoutRun,
    SignalSourceConfig,
)
from products.signals.backend.scout_harness.lazy_seed import canonical_structured_output_schema_for
from products.signals.backend.scout_harness.limits import MAX_RUN_NOTE_CHARS

logger = structlog.get_logger(__name__)

SAFETY_CHUNK_CHARS = 10_000
SAFETY_CHUNK_OVERLAP_CHARS = 1_000
MAX_SAFETY_CHUNKS = 40

REASON_UNSAFE_CONTENT = "unsafe_content"
REASON_INPUT_TOO_LARGE = "input_too_large"
REASON_ENTITY_GONE = "entity_gone"
REASON_RUN_IN_FLIGHT = "run_in_flight"
REASON_AGENT_RUN_FAILED = "agent_run_failed"
REASON_NO_OUTPUT = "no_output"
REASON_STALE = "stale"
REASON_WORKFLOW_START_FAILED = "workflow_start_failed"

_VERDICT_OUTCOMES: dict[str, AgentRunOutcome] = {
    "actionable": AgentRunOutcome.REPORTS,
    "not_actionable": AgentRunOutcome.NOT_ACTIONABLE,
    "needs_input": AgentRunOutcome.NEEDS_INPUT,
}


@frozen
class AgentScout:
    """The scout that runs for one agent and entity type, and the writes its runs may make."""

    skill_name: str
    write_scopes: tuple[str, ...]


@frozen
class _AgentScoutKey:
    agent: str
    product: str
    type: str


# Which skill handles an entity is a Self-driving setting, so a request never names a skill.
_AGENT_SCOUTS: dict[_AgentScoutKey, AgentScout] = {
    _AgentScoutKey(
        agent=SignalAgentRun.Agent.RESEARCH, product=SignalSourceProduct.CONVERSATIONS, type="ticket"
    ): AgentScout(skill_name=SUPPORT_TICKET_SCOUT, write_scopes=("ticket:write",)),
}


def agent_scout_for(agent: str, entity: AgentEntity) -> AgentScout | None:
    return _AGENT_SCOUTS.get(_AgentScoutKey(agent=agent, product=entity.product, type=entity.type))


def entity_of(run: SignalAgentRun) -> AgentEntity:
    return AgentEntity(product=run.source_product, type=run.source_type, id=run.source_id)


def entity_key(entity: AgentEntity) -> str:
    """One string for the entity, stamped on the scout run so runs of one entity can be found."""
    return f"{entity.product}:{entity.type}:{entity.id}"


def safety_chunks(text: str) -> list[str] | None:
    """The pieces of `text` to screen, or None when the text is too large to screen.

    A chunk is no larger than the ticket snapshot the signals lane screens
    (`emission.conversations_tickets.MAX_DESCRIPTION_CHARS`), so the safety model sees input of a
    size it already handles. Each chunk repeats the end of the one before it, so a payload that a
    boundary cuts in two is whole in one chunk. The count is capped so that one request cannot buy
    an unbounded number of safety calls, and an entity over the cap gets no agent.
    """
    if not text:
        return []
    step = SAFETY_CHUNK_CHARS - SAFETY_CHUNK_OVERLAP_CHARS
    chunks = [text[start : start + SAFETY_CHUNK_CHARS] for start in range(0, len(text), step)]
    # The last step can start inside the overlap of the chunk before it, which already holds that text.
    if len(chunks) > 1 and len(chunks[-1]) <= SAFETY_CHUNK_OVERLAP_CHARS:
        chunks.pop()
    return chunks if len(chunks) <= MAX_SAFETY_CHUNKS else None


def build_run_note(*, run: SignalAgentRun, url: str) -> str:
    """The note the scout run starts with. It names the entity and holds none of its content.

    The scout run row keeps the note, and people who can read scout runs are not always allowed to
    read the entity, so the entity's title and text stay out.
    """
    lines = [
        f"product: {run.source_product}",
        f"type: {run.source_type}",
        f"id: {run.source_id}",
        f"url: {url}",
        f"pass: {run.pass_number}",
    ]
    if run.reason:
        lines.append(f"reason: {run.reason}")
    if run.note:
        lines.append(f"note from the requester: {run.note}")
    return "\n".join(lines)[:MAX_RUN_NOTE_CHARS]


def ensure_agent_scout_config(team: Team, scout: AgentScout, entity: AgentEntity) -> SignalScoutConfig:
    """The config row the agent's scout runs under, created or brought up to date.

    The scout never runs on a schedule, so the row stays disabled. The run acts as the person who
    turned the entity's source on in Self-driving, because a scout run needs a person to act as and
    no person enabled this scout by hand.
    """
    source_enabler = (
        SignalSourceConfig.objects.filter(
            team_id=team.id,
            source_product=entity.product,
            source_type=SignalSourceConfig.config_source_type(entity.product, entity.type),
        )
        .select_related("created_by")
        .first()
    )
    enabler = source_enabler.created_by if source_enabler is not None else None
    if enabler is not None and not team.all_users_with_access().filter(pk=enabler.pk, is_active=True).exists():
        enabler = None
    schema = canonical_structured_output_schema_for(scout.skill_name)
    config, created = SignalScoutConfig.objects.unscoped().get_or_create(
        team_id=team.id,
        skill_name=scout.skill_name,
        defaults={
            "enabled": False,
            "emit": True,
            "created_by": enabler,
            "enabled_by": enabler,
            "write_scopes": list(scout.write_scopes),
            "structured_output_schema": schema,
        },
    )
    if created:
        return config
    changed: list[str] = []
    if config.structured_output_schema is None and schema is not None:
        config.structured_output_schema = schema
        changed.append("structured_output_schema")
    granted = config.write_scopes if isinstance(config.write_scopes, list) else []
    missing_scopes = [scope for scope in scout.write_scopes if scope not in granted]
    if missing_scopes:
        config.write_scopes = [*granted, *missing_scopes]
        changed.append("write_scopes")
    if config.enabled_by_id is None and enabler is not None:
        config.enabled_by = enabler
        changed.append("enabled_by")
    if changed:
        config.save(update_fields=changed)
    return config


@frozen
class AgentRunScoutContext:
    """What the scout runner needs to know about the agent run that started it."""

    agent_run_id: str
    entity_key: str
    steering: str


def load_agent_run_scout_context(*, team_id: int, agent_run_id: str) -> AgentRunScoutContext | None:
    run = SignalAgentRun.objects.for_team(team_id).filter(id=agent_run_id).first()
    if run is None:
        return None
    source_config = (
        SignalSourceConfig.objects.filter(
            team_id=run.team_id,
            source_product=run.source_product,
            source_type=SignalSourceConfig.config_source_type(run.source_product, run.source_type),
        )
        .values_list("config", flat=True)
        .first()
    )
    return AgentRunScoutContext(
        agent_run_id=str(run.id),
        entity_key=entity_key(entity_of(run)),
        steering=steering_from_config(source_config).text,
    )


def begin_pass(*, run_id: str) -> bool:
    """Mark the pass as running. False when the pass is settled already.

    A pass that is running already is marked again, because the step that calls this can be retried.
    """
    updated = SignalAgentRun.all_teams.filter(id=run_id, status__in=SignalAgentRun.ACTIVE_STATUSES).update(
        status=SignalAgentRun.Status.RUNNING, updated_at=timezone.now()
    )
    return updated == 1


def store_agent_run_output(*, team_id: int, agent_run_id: str, payload: dict[str, Any]) -> bool:
    """Keep the record the agent returned for its pass. A later record replaces an earlier one."""
    updated = (
        SignalAgentRun.objects.for_team(team_id)
        .filter(id=agent_run_id, status=SignalAgentRun.Status.RUNNING)
        .update(output=payload, updated_at=timezone.now())
    )
    return updated == 1


@frozen
class PassOutcome:
    outcome: AgentRunOutcome
    reason_code: str | None = None


def pass_outcome(
    *,
    ended_early: PassOutcome | None,
    scout_status: str | None,
    scout_skip_reason: str | None,
    output: dict[str, Any] | None,
) -> PassOutcome:
    """Decide how a pass ended from what its steps reported.

    `ended_early` is set when the pass stopped before the agent ran. `scout_status` is the status of
    the agent's task run, or None when the scout run never started.
    """
    if ended_early is not None:
        return ended_early
    if scout_status != "completed":
        # A skipped run has no status, and its skip reason says why it did not start.
        return PassOutcome(
            outcome=AgentRunOutcome.FAILED,
            reason_code=_reason_slug(scout_skip_reason) if scout_skip_reason else REASON_AGENT_RUN_FAILED,
        )
    outcome = _VERDICT_OUTCOMES.get(str((output or {}).get("verdict")))
    if outcome is None:
        return PassOutcome(outcome=AgentRunOutcome.FAILED, reason_code=REASON_NO_OUTPUT)
    return PassOutcome(outcome=outcome)


def _reason_slug(text: str) -> str:
    return "_".join(text.lower().replace("-", " ").split())[:60]


def _write_links(run: SignalAgentRun, scout_run: SignalScoutRun | None) -> None:
    if scout_run is None:
        return
    created = [str(report_id) for report_id in scout_run.emitted_report_ids or []]
    matched = [str(report_id) for report_id in scout_run.edited_report_ids or [] if str(report_id) not in created]
    relations = [
        *((report_id, SignalReportEntityLink.Relation.CREATED) for report_id in created),
        *((report_id, SignalReportEntityLink.Relation.MATCHED) for report_id in matched),
    ]
    SignalReportEntityLink.all_teams.bulk_create(
        [
            SignalReportEntityLink(
                team_id=run.team_id,
                report_id=report_id,
                source_product=run.source_product,
                source_type=run.source_type,
                source_id=run.source_id,
                relation=relation,
                agent_run=run,
            )
            for report_id, relation in relations
        ],
        # A follow-up pass can match a report that an earlier pass already linked.
        ignore_conflicts=True,
    )


def agent_run_result(run: SignalAgentRun) -> AgentRunResult:
    """The result of a finished pass, as the owning product's handler receives it."""
    stored = run.result or {}
    links = list(
        SignalReportEntityLink.all_teams.filter(
            team_id=run.team_id,
            source_product=run.source_product,
            source_type=run.source_type,
            source_id=run.source_id,
        ).order_by("created_at", "id")
    )
    return AgentRunResult(
        run_id=str(run.id),
        team_id=run.team_id,
        agent=run.agent,
        entity=entity_of(run),
        pass_number=run.pass_number,
        outcome=AgentRunOutcome(stored.get("outcome", AgentRunOutcome.FAILED)),
        reason_code=stored.get("reason_code"),
        next_pass_queued=bool(stored.get("next_pass_queued")),
        reports=attached_reports(team_id=run.team_id, links=links).get(run.source_id, ()),
        output=run.output,
    )


@frozen
class CompletedPass:
    """A settled pass, and the pass that a waiting request started, for the caller to dispatch.

    A retried caller gets `next_run_id` again while that pass is still queued, because the first
    attempt can stop before it dispatches.
    """

    result: AgentRunResult
    next_run_id: str | None


def _queued_next_pass_id(run: SignalAgentRun) -> str | None:
    next_id = (
        SignalAgentRun.all_teams.filter(
            team_id=run.team_id,
            agent=run.agent,
            source_product=run.source_product,
            source_type=run.source_type,
            source_id=run.source_id,
            pass_number=run.pass_number + 1,
            status=SignalAgentRun.Status.QUEUED,
        )
        .values_list("id", flat=True)
        .first()
    )
    return str(next_id) if next_id is not None else None


def complete_pass(
    *,
    run_id: str,
    outcome: PassOutcome,
    scout_run_id: str | None = None,
    keep_output: bool = True,
) -> CompletedPass | None:
    """Settle a pass: write its links and result, and queue one more pass if a request waited.

    Returns None when the row is gone. A pass that is already settled returns its stored result and
    starts nothing, so a retried caller delivers the same result again.
    """
    with transaction.atomic():
        run = SignalAgentRun.all_teams.select_for_update().filter(id=run_id).first()
        if run is None:
            return None
        if run.status not in SignalAgentRun.ACTIVE_STATUSES:
            return CompletedPass(result=agent_run_result(run), next_run_id=_queued_next_pass_id(run))

        scout_run = (
            SignalScoutRun.all_teams.filter(id=scout_run_id, team_id=run.team_id).first() if scout_run_id else None
        )
        if keep_output:
            _write_links(run, scout_run)
        else:
            run.output = None

        next_run: SignalAgentRun | None = None
        failed = outcome.outcome == AgentRunOutcome.FAILED
        run.status = SignalAgentRun.Status.FAILED if failed else SignalAgentRun.Status.DONE
        run.scout_run = scout_run
        run.finished_at = timezone.now()
        run.result = {
            "outcome": outcome.outcome.value,
            "reason_code": outcome.reason_code,
            "next_pass_queued": run.look_again,
        }
        run.save(update_fields=["status", "scout_run", "finished_at", "result", "output", "updated_at"])
        if run.look_again:
            next_run = SignalAgentRun.all_teams.create(
                team_id=run.team_id,
                agent=run.agent,
                source_product=run.source_product,
                source_type=run.source_type,
                source_id=run.source_id,
                pass_number=run.pass_number + 1,
                reason=run.reason,
                note=run.note,
                requested_by=run.requested_by,
            )
        return CompletedPass(
            result=agent_run_result(run), next_run_id=str(next_run.id) if next_run is not None else None
        )
