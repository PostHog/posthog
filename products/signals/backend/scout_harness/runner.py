from __future__ import annotations

import time
import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from django.db.models import F
from django.utils import timezone

import posthoganalytics
from croniter import CroniterError, croniter

from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7
from posthog.sync import database_sync_to_async

from products.business_knowledge.backend.logic import is_maintained_for_team
from products.data_catalog.backend.facade.api import approved_metric_names_for_team
from products.data_catalog.backend.facade.flags import is_data_catalog_enabled
from products.mcp_store.backend.facade.api import get_sandbox_mcp_server_names
from products.signals.backend.agent_runtime import STEP_SCOUT, resolve_agent_runtime
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.derived_metadata import stamp_derived_metadata
from products.signals.backend.scout_harness.lazy_seed import canonical_skill_names, sync_canonical_skills
from products.signals.backend.scout_harness.limits import (
    DEFAULT_MAX_RUNTIME_S,
    FAILURE_STREAK_MAX_RUNS,
    FAILURE_STREAK_MIN_SPAN_MINUTES,
    STALE_RUN_CUTOFF_S,
    failure_streak_pause_threshold,
    interval_runs_in_tolerance_window,
)
from products.signals.backend.scout_harness.model_selection import resolve_scout_model
from products.signals.backend.scout_harness.prompt import (
    HARNESS_PROMPT_VERSION,
    SignalScoutRunSummary,
    build_run_prompt,
)
from products.signals.backend.scout_harness.skill_loader import (
    SIGNALS_SCOUT_SKILL_PREFIX,
    LoadedSkill,
    load_skill_for_run,
    resolve_report_channel_variant,
    resolve_scout_acting_user_id,
    skill_uses_report_channel,
)
from products.signals.backend.scout_harness.team_limits import github_read_access_for_team, withheld_skills_for_team
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_acting_user_id_for_team,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession, TurnPollTimeout

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = logging.getLogger(__name__)

# Reuse the report-research sandbox env. Same posture: full repo on disk, restricted
# network, MCP read scopes injected. Split out later if the agent needs different policy.
SIGNALS_SCOUT_SANDBOX_ENV_NAME = SIGNALS_REPORT_RESEARCH_ENV_NAME

# Dedicated env for scouts whose config opts into full network access. Sandbox envs are
# per-team rows shared by name, and `upsert_internal_sandbox_env` reasserts policy on every
# call — so a full-network run must NOT reuse the shared research env above, or it would
# flip the network policy for report research and every trusted-mode scout on the team.
SIGNALS_SCOUT_FULL_NETWORK_ENV_NAME = "SIGNALS_SCOUT_FULL_NETWORK"

# Every scout `ai_stage` starts with this, so `ai_stage LIKE 'scout:%'` rolls the whole fleet
# up as one stage even though the tag names the individual scout.
SCOUT_AI_STAGE_PREFIX = "scout:"

# `_cron_runs_in_window` samples a cron schedule from a fixed reference (not `now`) so a lane's
# breaker threshold is a property of its schedule rather than of when it happened to fail. The
# horizon is one full pass of the month and day-of-month fields, which keeps cross-month
# adjacencies in the sample: "first of the month or Sunday" packs its fullest window where a
# matching Sunday touches a first, and a shorter occurrence-count sample never reaches one.
# Day-of-week alignments unique to other calendar years can still be missed, which only ever
# undercounts, so an exotic lane trips a little earlier instead of earning extra lease budget.
# The sample cap covers the horizon at the 30-minute schedule floor with room to spare; denser
# out-of-band schedules hit the `FAILURE_STREAK_MAX_RUNS` early exit long before it.
_CRON_WINDOW_REFERENCE = datetime(2026, 1, 1, tzinfo=UTC)
_CRON_WINDOW_HORIZON = timedelta(days=366)
_CRON_WINDOW_MAX_SAMPLES = 20_000

# Cron lanes hold wall-clock time in the project's timezone (see the coordinator's due-check),
# so on the spring-forward night more wall-clock schedule fits inside the same absolute outage
# than this transition-free sample sees. Sized to the largest jump among selectable project
# timezones (Antarctica/Troll advances two hours; every other zone is an hour or less), which
# keeps the tolerance honest on that night in every zone at the cost of at most a couple of
# extra tolerated failures the rest of the year. That is far cheaper than sizing per project
# timezone, which would put DST fold/gap arithmetic and a per-team cache key on the failure path.
_CRON_WINDOW_DST_SLACK_MINUTES = 120

# The report channel (emit_report/edit_report) is opt-in per skill. A scout's sandbox token
# carries the report-write scope ONLY when its skill listed one of these in `allowed_tools` (see
# the posture selection where the sandbox context is built). A baseline scout never carries that
# scope, so the MCP server strips the report tools from its toolset — they can't bleed into a run
# that didn't opt in. `views._assert_report_tool_opted_in` is the matching fail-closed gate on the
# write itself. `REPORT_CHANNEL_TOOLS` / `skill_uses_report_channel` live in `skill_loader` so the
# runner, prompt builder, and viewset all resolve the same opt-in set.


@dataclass(frozen=True)
class RunResult:
    """Outcome of a run-trigger.

    `run_id` / `task_run_id` are None when the trigger was skipped without
    persisting a row (e.g. another run for the same team/skill is still in
    flight). `status` mirrors `TaskRun.Status` values as strings so callers
    don't need to import the tasks model.
    """

    run_id: str | None
    task_run_id: str | None
    status: str | None
    last_message: str | None
    runtime_s: float
    skill_name: str
    skill_version: int
    skip_reason: str | None = None


def run_signals_scout(
    *,
    team_id: int,
    skill_name: str,
    skill_version: int | None = None,
    repository: str | None = None,
    verbose: bool = False,
    triggered_by: str = "schedule",
) -> RunResult:
    """Synchronous entrypoint: resolves config, spawns sandbox, persists the run row.

    Wraps the async core for callers that aren't inside an event loop (management
    command, direct script). Temporal activities call `arun_signals_scout` directly.
    """
    return asyncio.run(
        arun_signals_scout(
            team_id=team_id,
            skill_name=skill_name,
            skill_version=skill_version,
            repository=repository,
            verbose=verbose,
            triggered_by=triggered_by,
        )
    )


async def arun_signals_scout(
    *,
    team_id: int,
    skill_name: str,
    skill_version: int | None = None,
    repository: str | None = None,
    verbose: bool = False,
    triggered_by: str = "schedule",
) -> RunResult:
    """Async core. Safe to call from inside a running event loop (Temporal activity).

    `triggered_by` is `"schedule"` for coordinator-dispatched runs (including breaker probes)
    and `"manual"` for on-demand triggers (the `run` endpoint, the management command). Only
    scheduled failures feed the failure-streak breaker; see the failure path below.
    """
    team = await database_sync_to_async(_get_team, thread_sensitive=False)(team_id)

    # Honor the per-scout holdback denylist, resolved against the canonical project. Two effects:
    # (1) a direct run of a held-back scout is refused up front (so this manual path can't seed or
    # run a scout the flag withholds), and (2) the canonical sync below is passed the denylist so
    # running *any* scout on a held-back team can't seed the other withheld scouts' rows as a side
    # effect. In local dev there's no flag payload, so this resolves empty and nothing is blocked.
    withheld = await database_sync_to_async(withheld_skills_for_team, thread_sensitive=False)(
        team.parent_team_id or team.id
    )
    if skill_name in withheld:
        logger.info(
            "signals_scout: skipping run, scout is withheld from this team",
            extra={"team_id": team_id, "skill_name": skill_name},
        )
        return RunResult(
            run_id=None,
            task_run_id=None,
            status=None,
            last_message=None,
            runtime_s=0.0,
            skill_name=skill_name,
            skill_version=skill_version or 0,
            skip_reason="scout is withheld from this team",
        )

    # Sync canonical signals-scout-* skills before we resolve the skill the run asked for.
    # Creates rows for newly-shipped specialists, updates harness-seeded rows the team
    # hasn't edited, and leaves forked / tombstoned rows alone. Failures here should not
    # crash the run — we log and continue with whatever skills the team already has.
    try:
        await database_sync_to_async(sync_canonical_skills, thread_sensitive=False)(team, withheld_skill_names=withheld)
    except Exception:
        logger.exception(
            "signals_scout: canonical skill sync failed; continuing with existing team skills",
            extra={"team_id": team_id},
        )
    skill = await database_sync_to_async(load_skill_for_run, thread_sensitive=False)(
        team, skill_name, version=skill_version, include_authors=True
    )
    config = await database_sync_to_async(_resolve_config, thread_sensitive=False)(team, skill.name)

    # Stale-run recovery, before the skip-if-running guard below. A scout run writes its own
    # terminal `task_run.status` from inside the activity; if the worker/sandbox dies hard
    # mid-run that write never lands, leaving the TaskRun stuck `IN_PROGRESS` — which would
    # otherwise block every future dispatch for this `(team, skill)` forever via
    # `_has_running_run`. Reap such orphans here so the lane self-heals. Keyed on the same
    # canonical `(team, skill_name)` the guard uses so it reaps exactly the rows the guard sees.
    await database_sync_to_async(_self_heal_stale_runs, thread_sensitive=False)(
        team.parent_team_id or team.id, skill.name
    )

    # Skip-if-running guard, keyed on (team, skill_name). Different skills for the same
    # team are allowed to run concurrently — the coordinator can dispatch several due
    # scouts for one team in a single tick. Best-effort — there is a race window between
    # this check and the bridge-row insert inside _spawn_and_run (a second trigger could
    # land in between), which we accept until a claim/lease primitive lands.
    if await database_sync_to_async(_has_running_run, thread_sensitive=False)(
        team_id=team.parent_team_id or team.id, skill_name=skill.name
    ):
        logger.info(
            "signals_scout: skipping trigger, prior run still in progress",
            extra={"team_id": team_id, "skill_name": skill.name},
        )
        return RunResult(
            run_id=None,
            task_run_id=None,
            status=None,
            last_message=None,
            runtime_s=0.0,
            skill_name=skill.name,
            skill_version=skill.version,
            skip_reason="prior run still in progress",
        )

    # Resolve the acting user up front: the skill's creator (else the config's enabler/creator)
    # when one resolves, so a scout's runs, and the AI spend attributed off the task row, land on
    # the human who authored or enabled the scout instead of pooling on one team-level default
    # user. Scouts don't clone a repo on the cadence path, so they don't need a GitHub integration
    # — the `resolve_acting_user_id_for_team` fallback prefers the GitHub creator when present but
    # falls back to any active org member, so a team that never connected GitHub still runs (these
    # dominated the fleet failure rate when the run instead crashed ~5s into `_spawn_and_run` and
    # booked a bogus `failed`). The only remaining short-circuit is the genuine "no active user to
    # act as" case; like the withheld / in-flight skips it leaves no row, no lifecycle event, and
    # a `skip_reason` the coordinator can surface — not a failure.
    user_id = await database_sync_to_async(resolve_scout_acting_user_id, thread_sensitive=False)(
        team, skill.name, config
    )
    if user_id is None:
        user_id = await database_sync_to_async(resolve_acting_user_id_for_team, thread_sensitive=False)(team.id)
    if user_id is None:
        logger.info(
            "signals_scout: skipping run, no active user to act as for team",
            extra={"team_id": team_id, "skill_name": skill.name},
        )
        return RunResult(
            run_id=None,
            task_run_id=None,
            status=None,
            last_message=None,
            runtime_s=0.0,
            skill_name=skill.name,
            skill_version=skill.version,
            skip_reason="no active user to act as for team",
        )

    started = time.monotonic()
    # Pre-mint the bridge row's UUID so the prompt can reference it before the row
    # exists. The TaskRun is created inside `MultiTurnSession.start`; the bridge row is
    # inserted via its `on_task_run_created` hook — after the TaskRun exists but before
    # the agent's first turn — so first-turn finding emits can resolve the run by id.
    run_id = uuid7()
    started_at = timezone.now()

    # Resolve the scout's agent model. A `None` model keeps the agent-server default; an override
    # routes this run on that model, paired with the runtime adapter that can serve it (the agent
    # server can't route a model without one). Two flag-gated layers, resolved in one call: the
    # scout's own `config.model` pin (honored while the `scouts-model-config` dogfood flag is on
    # for the team, deterministic per scout), then the `scouts-model-selection` payload — a
    # per-team, per-scout model distribution, bucketed per run on `run_id`, so a scout can A/B/n
    # across models against itself across runs. Resolved once here so the whole run is consistent.
    # Off the event loop — the flag reads do blocking network I/O.
    scout_model = await database_sync_to_async(resolve_scout_model, thread_sensitive=False)(
        team, skill.name, str(run_id), configured_model=config.model
    )

    # The scout-model resolution (config pin, then experiment gate) sits above the
    # `signals-pipeline-models` runtime pin, the default layer beneath it. When it resolves a model
    # for this run it wins (the gate's unallocated remainder resolves None and falls through to the
    # pin), so a fleet-wide pin can't silently swallow a configured model. Either way the whole
    # runtime/model/effort triple is taken from one source — a Codex runtime never pairs with a
    # model it can't serve. Model-only pin entries are still ignored for scout: a pin supplies
    # model+runtime as a pair, and overriding one without the other would mis-route.
    agent_runtime = await database_sync_to_async(resolve_agent_runtime, thread_sensitive=False)(team_id, STEP_SCOUT)
    if scout_model.model:
        runtime_adapter: str | None = scout_model.runtime_adapter
        model: str | None = scout_model.model
        reasoning_effort: str | None = scout_model.reasoning_effort
    elif agent_runtime.runtime_adapter:
        runtime_adapter = agent_runtime.runtime_adapter
        model = agent_runtime.model
        reasoning_effort = agent_runtime.reasoning_effort
    else:
        runtime_adapter = None
        model = None
        reasoning_effort = None
    # Resolved here rather than inside `_spawn_and_run` so the failure and cancellation paths below
    # can report the same prompt shape the run actually got: a spawn that raises never returns, so a
    # value resolved in there would be unavailable to exactly the runs whose shape matters most.
    # The `gh` guidance is gated on report-channel scouts whose team passes the `github_read_access`
    # posture in the `signals-scout` flag payload (default on; per-team or fleet-wide `false` is the
    # kill switch, resolved against the canonical project id) AND a mint preflight, since the prompt
    # must not name `gh` when the team has no usable installation to mint from (the scout would burn
    # budget on 401s before falling back). Repo-backed runs (the management command's `--repository`
    # escape hatch) are excluded too: they take the full-credential provisioning path, and the
    # section's read-only framing would misdescribe the token they actually hold.
    github_guidance = (
        skill_uses_report_channel(skill.allowed_tools)
        and repository is None
        and await database_sync_to_async(github_read_access_for_team, thread_sensitive=False)(
            team.parent_team_id or team.id
        )
    )
    if github_guidance:
        github_guidance = await database_sync_to_async(
            tasks_facade.can_mint_readonly_github_token, thread_sensitive=False
        )(team.id)
    # Resolved here alongside `github_guidance`, and for the same reason: it forks the prompt, so
    # the failure and cancellation paths below must report the same shape the run got, and a value
    # resolved inside `_spawn_and_run` would be missing on exactly the runs that raised before
    # reaching it. The helper never raises (it swallows read errors to off), so it is safe outside
    # the try. Whether the business-knowledge section rendered rides on this boolean.
    business_knowledge_maintained = await database_sync_to_async(
        _business_knowledge_maintained_for_team, thread_sensitive=False
    )(team)
    try:
        last_message, task_run_id = await _spawn_and_run(
            team=team,
            config=config,
            run_id=run_id,
            started_at=started_at,
            skill=skill,
            repository=repository,
            verbose=verbose,
            user_id=user_id,
            github_guidance=github_guidance,
            business_knowledge_maintained=business_knowledge_maintained,
            model=model,
            runtime_adapter=runtime_adapter,
            reasoning_effort=reasoning_effort,
        )
        runtime_s = time.monotonic() - started
        emitted_count, _ = await database_sync_to_async(_read_run_metrics, thread_sensitive=False)(
            run_id, team.parent_team_id or team.id
        )
        # A run that got all the way through closes the breaker: the lane works, so any streak
        # it had accumulated is stale and a standing auto-pause is lifted (this is also how the
        # half-open probe recovers a paused lane once its underlying cause is fixed). Any
        # trigger counts, since a manual success is the natural way to revive a lane right
        # after fixing its skill.
        await database_sync_to_async(_clear_failure_streak, thread_sensitive=False)(config.pk)
        _capture_run_finished(
            team=team,
            config=config,
            skill=skill,
            github_guidance=github_guidance,
            business_knowledge_maintained=business_knowledge_maintained,
            run_id=run_id,
            task_run_id=task_run_id,
            status=tasks_facade.TaskRunStatus.COMPLETED.value,
            runtime_s=runtime_s,
            emitted_count=emitted_count,
            model=model,
            runtime_adapter=runtime_adapter,
        )
        return RunResult(
            run_id=str(run_id),
            task_run_id=task_run_id,
            status=tasks_facade.TaskRunStatus.COMPLETED.value,
            last_message=last_message,
            runtime_s=runtime_s,
            skill_name=skill.name,
            skill_version=skill.version,
        )
    except Exception as exc:
        runtime_s = time.monotonic() - started
        # A failure before the on_task_run_created hook fires means no row was persisted —
        # don't hand callers a run_id that resolves to nothing.
        row_persisted = await database_sync_to_async(_run_row_exists, thread_sensitive=False)(
            run_id, team.parent_team_id or team.id
        )
        # Fail safe and silent: the TaskRun MultiTurnSession spans carries the error
        # context (status=FAILED, error_message, full chat log via LLMA). Nothing
        # additional to persist on the bridge row.
        logger.exception(
            "signals_scout: run failed",
            extra={
                "team_id": team_id,
                "run_id": str(run_id),
                "skill_name": skill.name,
                "row_persisted": row_persisted,
            },
        )
        # A partial run can still have emitted (and have a linked TaskRun) before failing,
        # so read both from the bridge row when it exists; otherwise it never ran far
        # enough to persist either.
        emitted_count, failed_task_run_id = (
            await database_sync_to_async(_read_run_metrics, thread_sensitive=False)(
                run_id, team.parent_team_id or team.id
            )
            if row_persisted
            else (0, None)
        )
        # Advance the breaker before the event so the failure that trips it is the one whose
        # `error_message` explains the pause. Scheduled failures only: the threshold is sized
        # on the schedule's cadence, so counting off-schedule "run now" retries would let a
        # burst of them reach a slow lane's threshold in minutes and impose the probe cooldown
        # on a lane whose schedule never failed.
        streak = (
            await database_sync_to_async(_record_failure_streak, thread_sensitive=False)(config.pk)
            if triggered_by == "schedule"
            else None
        )
        _capture_run_finished(
            team=team,
            config=config,
            skill=skill,
            github_guidance=github_guidance,
            business_knowledge_maintained=business_knowledge_maintained,
            run_id=run_id,
            task_run_id=failed_task_run_id,
            status=tasks_facade.TaskRunStatus.FAILED.value,
            runtime_s=runtime_s,
            emitted_count=emitted_count,
            model=model,
            runtime_adapter=runtime_adapter,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
            extra_properties=_poll_timeout_properties(exc),
        )
        if streak is not None and streak.tripped:
            _capture_config_auto_paused(
                team=team,
                config=config,
                skill_name=skill.name,
                run_id=run_id,
                failure_count=streak.count,
                failure_streak_threshold=streak.threshold,
                reason=str(exc)[:300],
            )
        return RunResult(
            run_id=str(run_id) if row_persisted else None,
            task_run_id=None,
            status=tasks_facade.TaskRunStatus.FAILED.value,
            last_message=None,
            runtime_s=runtime_s,
            skill_name=skill.name,
            skill_version=skill.version,
        )
    except BaseException as exc:
        # Cancellation / worker-shutdown / system-exit: re-raise so Temporal sees the
        # activity as failed. Post-collapse the bridge row's status flows from its
        # linked TaskRun (managed by MultiTurnSession), so we don't update anything
        # here directly. A TaskRun stranded in IN_PROGRESS (e.g. SIGKILL before
        # MultiTurnSession finalizes) blocks new runs for this (team, skill) via
        # `_has_running_run` until it transitions out — active recovery is a deferred
        # follow-up (see `_self_heal_stale_runs`).
        runtime_s = time.monotonic() - started
        logger.warning(
            "signals_scout: run cancelled mid-flight",
            extra={
                "team_id": team_id,
                "run_id": str(run_id),
                "skill_name": skill.name,
                "exception_type": type(exc).__name__,
                "runtime_s": runtime_s,
            },
        )
        # Synchronous, no DB read — the loop is collapsing, so don't await anything here;
        # `emitted_count` is left unknown rather than risk a query during cancellation. The
        # failure-streak breaker is deliberately untouched too: a cancelled run says nothing
        # about whether this lane can succeed, and counting worker shutdowns toward the streak
        # would pause healthy scouts after a few deploys.
        _capture_run_finished(
            team=team,
            config=config,
            skill=skill,
            github_guidance=github_guidance,
            business_knowledge_maintained=business_knowledge_maintained,
            run_id=run_id,
            task_run_id=None,
            status=tasks_facade.TaskRunStatus.CANCELLED.value,
            runtime_s=runtime_s,
            emitted_count=None,
            model=model,
            runtime_adapter=runtime_adapter,
        )
        raise


def _data_catalog_enabled_for_team(team: Team) -> bool:
    """Whether this team's scouts get the governed-metrics catalog steering.

    A flag-read error falls back to off rather than propagating: this resolves inside the
    `_spawn_and_run` call the outer handler treats as a failed run, so a transient SDK or
    cache error would book a failure and advance the streak toward pausing the lane, over a
    prompt section the run does not need. Mirrors `team_limits._read_flag_payload`, where a
    read error never breaks dispatch either. Off is also the pre-catalog behaviour, so the
    fallback can only cost steering, never mis-steer a team at a table it cannot query.
    """
    try:
        return is_data_catalog_enabled(team)
    except Exception as error:
        capture_exception(error)
        return False


def _business_knowledge_maintained_for_team(team: Team) -> bool:
    """Whether this team's scouts get the business-knowledge section.

    `is_maintained_for_team`, not `is_available_for_team`: the section rides on every run, so a
    knowledge base a team tried once and abandoned would tax the whole lane forever. Resolved
    fresh per run so a flag flip, a first finished ingest, or a team returning to curate lands on
    the next run. Falls back to off on a read error for the same reason
    `_data_catalog_enabled_for_team` does: the resolved value forks the prompt and is stamped on
    the run row + both lifecycle events, so a raise would book a failed run and advance the streak
    over a section the run does not need. Swallowing here also keeps it safe to resolve in
    `arun_signals_scout` (outside the run's try/except), where the failure and cancellation paths
    read it back to report the shape the run got.
    """
    try:
        return is_maintained_for_team(team)
    except Exception as error:
        capture_exception(error)
        return False


def _governed_metric_names_for_team(team: Team, user_id: int) -> list[str] | None:
    """Approved metric names for prompt injection, or None when the read fails.

    Resolved as the run's acting user, the same identity the sandbox's MCP token carries, so the
    injected listing can never be wider than what the run could have queried for itself through
    `system.information_schema.metrics`.
    """
    try:
        return approved_metric_names_for_team(team, User.objects.get(id=user_id))
    except Exception as error:
        capture_exception(error)
        return None


def _mcp_server_names_for_run(team: Team, user_id: int, config: SignalScoutConfig) -> list[str]:
    """Names of the external MCP servers this run's sandbox will mount, for prompt steering.

    Mirrors the launch path's resolution parameter for parameter (`start_agent_server` →
    `get_installations_for_sandbox`): same origin and agent key, no credential owner, the
    per-scout server selection, and the personal-inclusion posture of a non-internal task —
    so the prompt names exactly the servers the sandbox mounts. A resolution error degrades
    to an empty list rather than propagating, for the same reason as the flag fallback above:
    the servers still mount (or not) at launch regardless, so the fallback only costs steering.
    """
    try:
        return get_sandbox_mcp_server_names(
            team.id,
            user_id=user_id,
            include_personal=True,
            task_origin=tasks_facade.TaskOriginProduct.SIGNALS_SCOUT,
            task_agent_key="scout",
            credential_owner_id=None,
            allowed_gateway_server_ids=[str(server_id) for server_id in (config.mcp_gateway_server_ids or [])],
        )
    except Exception as error:
        capture_exception(error)
        return []


async def _spawn_and_run(
    *,
    team: Team,
    config: SignalScoutConfig,
    run_id: Any,
    started_at: Any,
    skill: LoadedSkill,
    repository: str | None,
    verbose: bool,
    user_id: int,
    github_guidance: bool,
    business_knowledge_maintained: bool,
    model: str | None,
    runtime_adapter: str | None = None,
    reasoning_effort: str | None = None,
) -> tuple[str, str]:
    """Spawn the sandbox, create the bridge row before the first turn, run the agent.

    `user_id` is the acting user resolved (and validated non-None) by the caller. `model`,
    `runtime_adapter`, and `reasoning_effort` are the agent runtime overrides (`model` paired with the
    `runtime_adapter` that serves it — the agent server derives the provider from it; all `None` keeps
    the agent-server default Claude runtime). Returns `(last_message, task_run_id)`.
    """
    # The config's `network_access` picks the sandbox env — and with it the egress policy the
    # provisioning layer enforces. Trusted (default) shares the research env; full gets its own
    # env name so its unrestricted policy can't be reasserted onto the shared one.
    if config.network_access == SignalScoutConfig.NetworkAccess.FULL:
        sandbox_env_name = SIGNALS_SCOUT_FULL_NETWORK_ENV_NAME
        network_access_level = tasks_facade.SandboxNetworkAccessLevel.FULL
    else:
        sandbox_env_name = SIGNALS_SCOUT_SANDBOX_ENV_NAME
        network_access_level = tasks_facade.SandboxNetworkAccessLevel.TRUSTED
    sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
        team.id,
        sandbox_env_name,
        network_access_level,
    )
    report_channel = skill_uses_report_channel(skill.allowed_tools)
    # Scout sandboxes never get the write-capable installation token: task creation attaches the
    # team's GitHub integration to every task, so without this request a repo-less scout run on a
    # GitHub-connected team is silently provisioned with the FULL token. Requesting read access on
    # every scout run downscopes that to a read-only mint (or nothing when the mint fails) —
    # a strict privilege reduction, independent of the prompt-guidance flag below.
    #
    # The `gh` guidance in the prompt is gated separately: report-channel scouts only, the
    # `github_read_access` posture in the `signals-scout` flag payload (default on; per-team or
    # fleet-wide `false` is the kill switch — resolved against the canonical project id, like
    # every flag-payload lookup), AND a mint preflight — the prompt must not name `gh` when the
    # team has no usable installation to mint from (the scout would burn budget on 401s before
    # falling back). Repo-backed runs (the management command's `--repository` escape hatch) are
    # excluded too: they take the full-credential provisioning path, and the section's read-only
    # framing would misdescribe the token they actually hold.
    # `repository` is None on the cadence path — v1 doesn't clone a repo into the
    # sandbox. The kwarg stays wired so the management command can still pass
    # `--repository` for ad-hoc local investigations; productionised repo access
    # is deferred (see implementation plan).
    context = CustomPromptSandboxContext(
        team_id=team.id,
        user_id=user_id,
        repository=repository,
        sandbox_environment_id=sandbox_env_id,
        # `signals_scout` is the harness's own scope posture: project reads +
        # INTERNAL_SCOPES + the scout's `signal_scout_internal:write`, plus a narrow
        # allowlist of user-facing writes (`SCOUT_USER_WRITE_SCOPES`, e.g.
        # `notebook:write`) so a finding can produce a durable artifact. It reports
        # `has_write_scopes=True` so the MCP server doesn't enable read-only-mode tool
        # filtering. Without that opt-out, the MCP layer would categorically strip every
        # tool annotated `readOnlyHint: false` — including the agent's own `remember`,
        # `forget`, and `emit_finding` tools — even though the OAuth token does carry the
        # right scope to call them.
        #
        # A scout that opted into the report channel gets `signals_scout_reports` instead —
        # the same posture plus `signal_scout_report:write` — so the MCP server exposes the
        # emit_report/edit_report tools. Every other scout gets plain `signals_scout` and never
        # sees them.
        posthog_mcp_scopes=("signals_scout_reports" if report_channel else "signals_scout"),
        github_read_access=True,
        # `None` keeps the agent-server default; an override pins the whole run on one model
        # (the `scouts-model-selection` gate routes it here). The model the gateway actually serves
        # is tagged on each $ai_generation, so per-run model is queryable in LLM analytics.
        model=model,
        # Paired with `model`: the agent server derives the LLM provider from the runtime.
        runtime_adapter=runtime_adapter,
        reasoning_effort=reasoning_effort,
    )
    data_catalog_enabled = await database_sync_to_async(_data_catalog_enabled_for_team, thread_sensitive=False)(team)
    governed_metric_names = (
        await database_sync_to_async(_governed_metric_names_for_team, thread_sensitive=False)(team, user_id)
        if data_catalog_enabled
        else None
    )
    mcp_server_names = await database_sync_to_async(_mcp_server_names_for_run, thread_sensitive=False)(
        team, user_id, config
    )
    prompt = build_run_prompt(
        skill,
        run_id=str(run_id),
        team_id=team.id,
        started_at=started_at,
        github_read_access=github_guidance,
        data_catalog_enabled=data_catalog_enabled,
        governed_metric_names=governed_metric_names,
        # Names the external MCP servers the sandbox will mount, so *How to call tools* can carve
        # them out of the exec-interface rule; empty renders nothing.
        mcp_server_names=mcp_server_names,
        business_knowledge_maintained=business_knowledge_maintained,
        # Renders the structured-output section (schema + `scout-record-output` contract) only
        # when the config carries a schema AND emit is on — records land solely as project
        # events, so a dry-run scout must not be steered at a tool that fails closed.
        structured_output_schema=(config.structured_output_schema if config.emit else None),
    )
    logger.info(
        "signals_scout: spawning sandbox",
        extra={
            "team_id": team.id,
            "skill_name": skill.name,
            "skill_version": skill.version,
            "skill_id": skill.skill_id,
            "allowed_tools": skill.allowed_tools,
        },
    )

    async def _create_bridge_row(task_run: TaskRun) -> None:
        # Create the bridge row after the TaskRun exists but BEFORE the agent's first
        # turn runs (via MultiTurnSession's on_task_run_created hook). The scout is
        # single-turn and may call `scout-emit-signal` during that first turn;
        # the emit endpoint resolves the run by id, so the row must already exist or
        # first-turn emits 404. Creating it here (not after `start()` returns) also keeps
        # the cross-link queryable mid-run and surviving both success and failure exits.
        await database_sync_to_async(_create_run_row, thread_sensitive=False)(
            run_id=run_id,
            task_run=task_run,
            team=team,
            config=config,
            skill=skill,
            model=model,
            runtime_adapter=runtime_adapter,
            reasoning_effort=reasoning_effort,
            github_guidance=github_guidance,
            business_knowledge_maintained=business_knowledge_maintained,
        )
        # Lifecycle start marker. The row + TaskRun now exist and the run has cleared the
        # reap + single-flight guards, so this counts exactly the runs that actually start —
        # a skipped dispatch emits nothing. Pairs with `signals_scout_run_finished` for
        # event-derived throughput and stall detection (started with no finished = a run
        # that died before finalize), with no warehouse-sync lag.
        _capture_run_started(
            team=team,
            config=config,
            skill=skill,
            github_guidance=github_guidance,
            business_knowledge_maintained=business_knowledge_maintained,
            run_id=run_id,
            task_run_id=str(task_run.id),
            model=model,
            runtime_adapter=runtime_adapter,
        )

    session, result = await MultiTurnSession.start(
        prompt=prompt,
        context=context,
        model=SignalScoutRunSummary,
        step_name=_step_name(skill),
        verbose=verbose,
        origin_product=tasks_facade.TaskOriginProduct.SIGNALS_SCOUT,
        mcp_builtin_agent_key="scout",
        # No credential owner on purpose: a scout is a team resource, so its runs mount only
        # connections members shared to the whole team, never anyone's personal grants. That
        # keeps runs identical no matter who created or edits the scout, and covers ownerless
        # coordinator-discovered scouts. The per-scout selection below picks which of those
        # team-shared servers this scout's runs mount. Empty selects none.
        mcp_gateway_server_ids=[str(server_id) for server_id in (config.mcp_gateway_server_ids or [])],
        # Tag every scout $ai_generation with its stage AND its scout, so scout spend is both
        # splittable out of the ai_product='signals' bucket (scouts carry no signal_report_id)
        # and attributable to one scout. `ai_stage` is the only run-shaped value the harness
        # controls that reaches $ai_generation — the rest of the properties there are stamped
        # by the agent server off the task row. Team attribution rides along as `team_id`.
        ai_stage=_ai_stage(skill),
        on_task_run_created=_create_bridge_row,
        # Keep the per-turn poll budget at the run's runtime cap so the dropped-finalization
        # salvage fires before the activity's `start_to_close_timeout` (DEFAULT_MAX_RUNTIME_S +
        # ACTIVITY_SLACK_S) cancels the activity. Default budget (MAX_POLL_SECONDS) exceeds the
        # ceiling and would let the activity die before salvage could return the written summary.
        max_poll_seconds=DEFAULT_MAX_RUNTIME_S,
        # The close-out is free-text markdown — if the agent ends with prose or malformed JSON
        # instead of a SignalScoutRunSummary object, keep the raw text as the summary rather than
        # failing the whole run. A failed run never finalizes, so its scan-position close-out is
        # lost and the next run inherits a doubled scan delta.
        fallback_from_text=lambda text: SignalScoutRunSummary(summary=text),
    )
    try:
        # Persist the agent's end-of-turn close-out so non-emitting runs leave a
        # discoverable trace for future-run dedupe. Failure paths skip this on
        # purpose — the bridge row keeps its empty default and the linked TaskRun
        # carries the error context.
        await database_sync_to_async(_finalize_run_row, thread_sensitive=False)(
            run_id=run_id,
            team_id=team.parent_team_id or team.id,
            summary=result.summary,
        )
        return result.summary, str(session.task_run.id)
    finally:
        await session.end()


def _get_team(team_id: int) -> Team:
    return Team.objects.select_related("organization").get(id=team_id)


def _resolve_config(team: Team, skill_name: str) -> SignalScoutConfig:
    """Get-or-create the (team, skill) config row, keyed on the canonical (parent) team.

    `get_or_create`'s lookup half isn't canonicalized by the TeamScopedRootMixin `save()`,
    so resolve to the parent id ourselves — else a child-team lookup misses the stored row
    and tries to create a duplicate, raising IntegrityError on the unique constraint.
    """
    config, _ = SignalScoutConfig.objects.unscoped().get_or_create(
        team_id=team.parent_team_id or team.id, skill_name=skill_name
    )
    return config


def _has_running_run(*, team_id: int, skill_name: str) -> bool:
    # Locked on (canonical team, skill_name) — different skills for the same team are
    # allowed to fan out (the coordinator can dispatch several due scouts per tick). Status flows
    # from the linked TaskRun now that SignalScoutRun is just a bridge; treat both QUEUED
    # and IN_PROGRESS as active, since a TaskRun sits in QUEUED before transitioning and a
    # second trigger landing in that window would otherwise slip past the guard. Not keyed
    # on `scout_config_id`: configs are `on_delete=SET_NULL`, so a config delete/recreate
    # mid-run would orphan the FK and silently defeat the dedupe in exactly the
    # config-churn case it should still cover.
    return (
        SignalScoutRun.objects.unscoped()
        .filter(
            team_id=team_id,
            skill_name=skill_name,
            task_run__status__in=(tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.IN_PROGRESS),
        )
        .exists()
    )


def _self_heal_stale_runs(team_id: int, skill_name: str) -> None:
    """Reap orphaned in-flight runs so a dead run can't block the lane forever.

    A scout run writes its own terminal `task_run.status` from inside the activity. If the
    worker / sandbox dies hard mid-run (SIGKILL, pod eviction, sandbox loss), that write
    never lands and the TaskRun is frozen at `QUEUED`/`IN_PROGRESS`. `_has_running_run`
    then single-flights against that frozen row and skips every future dispatch for this
    `(team, skill)` indefinitely — there is no other release. Nothing else reconciles it:
    Temporal has already torn the workflow down (the activity is killed at
    `WORKFLOW_HARD_CEILING_S` with `maximum_attempts=1`), and the Tasks cleanup path does
    not cover a crashed worker.

    A run older than `STALE_RUN_CUTOFF_S` (a generous multiple of that ceiling) cannot
    still be legitimately executing, so it is an orphan and we mark it failed. The cutoff's
    slack means a run merely at the wall — about to fail or finish on its own — is never
    reaped out from under itself. Best-effort and silent: a failure to reap one row must
    never block the new run, so each is guarded independently.
    """
    cutoff = timezone.now() - timedelta(seconds=STALE_RUN_CUTOFF_S)
    stale_runs = list(
        SignalScoutRun.objects.unscoped()
        .filter(
            team_id=team_id,
            skill_name=skill_name,
            task_run__status__in=(tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.IN_PROGRESS),
            task_run__created_at__lt=cutoff,
        )
        .select_related("task_run")
    )
    if not stale_runs:
        return
    # Resolve the team once, only when there is actually something to reap, so the reaped
    # event carries the same team / groups shape as the other scout lifecycle events.
    team = _get_team(team_id)
    now = timezone.now()
    for run in stale_runs:
        try:
            task_run = run.task_run
            # Read the pre-reap status / age off the loaded bridge instance before the claim:
            # the conditional update below doesn't refresh it, so these stay the original values.
            status_before = task_run.status
            age_seconds = (now - task_run.created_at).total_seconds()
            # Compare-and-set claim on the status transition. Two triggers for the same
            # `(team, skill)` can reach this self-heal concurrently and load the same stale
            # row; the conditional UPDATE lets exactly one win — the other matches zero rows
            # once the first commits `FAILED`. Only the winner falls through to emit, so a
            # single stranded run can't double-count in the worker-death / mass-stall signal.
            claimed = tasks_facade.claim_and_fail_stale_run(
                task_run.id,
                "Scout run abandoned: no terminal status past the runtime ceiling "
                "(worker/sandbox lost before finalize).",
                error_type="stale_run_reaped",
            )
            if not claimed:
                continue
            logger.warning(
                "signals_scout: reaped stale in-progress run before dispatch",
                extra={
                    "team_id": team_id,
                    "skill_name": skill_name,
                    "run_id": str(run.id),
                    "task_run_id": str(run.task_run_id),
                },
            )
            # A reaped run never reaches the finalize path, so it emits no
            # `signals_scout_run_finished`. This event makes the strand observable with no
            # warehouse lag — a spike is the worker-death / mass-stall shape, caught within a
            # tick of the cutoff rather than days late.
            _capture_run_reaped(
                team=team,
                skill_name=skill_name,
                run_id=run.id,
                task_run_id=str(run.task_run_id),
                status_before=status_before,
                age_seconds=age_seconds,
            )
        except Exception:
            logger.exception(
                "signals_scout: failed to reap stale in-progress run; continuing",
                extra={"team_id": team_id, "skill_name": skill_name, "run_id": str(run.id)},
            )


def _create_run_row(
    *,
    run_id: Any,
    task_run: TaskRun,
    team: Team,
    config: SignalScoutConfig,
    skill: LoadedSkill,
    model: str | None = None,
    runtime_adapter: str | None = None,
    reasoning_effort: str | None = None,
    github_guidance: bool = False,
    business_knowledge_maintained: bool = False,
) -> SignalScoutRun:
    # Stamp the routed model triple onto the row's `metadata` so "which model ran this?" is a
    # column read on the run API, not an analytics-event join. Keys are omitted (not null-valued)
    # on the default path, so their absence means the agent-server default served the run.
    metadata: dict[str, Any] = {
        key: value
        for key, value in (
            ("model", model),
            ("runtime_adapter", runtime_adapter),
            ("reasoning_effort", reasoning_effort),
        )
        if value is not None
    }
    # Stamped only when non-default, like the model triple: absence means the run held the
    # trusted-domains posture. Stamped (rather than read off the config later) because the
    # config row can be edited after the fact, which would silently rewrite what past runs
    # could actually reach.
    if config.network_access == SignalScoutConfig.NetworkAccess.FULL:
        metadata["network_access"] = config.network_access
    # The three dimensions that pin down which instructions this run actually got. All are
    # point-in-time facts that become unrecoverable later, which is why they are stamped rather
    # than resolved at read time: the harness prompt has no version history, a skill's
    # `allowed_tools` can be edited (so an old run's channel can't be re-derived), and a seeded
    # canonical row flips to `custom` the moment a team edits it, taking every past run's origin
    # with it. Together they let runs be compared only against runs that got the same prompt
    # shape, which is what a model or prompt A/B needs to hold constant.
    metadata["harness_prompt_version"] = HARNESS_PROMPT_VERSION
    metadata["report_channel"] = resolve_report_channel_variant(skill.allowed_tools)
    metadata["skill_origin"] = skill.origin
    # Whether the run got the gh evidence section, which `_spawn_and_run` includes or omits from
    # the whole prompt based on the team's flag posture and whether a read-only token could be
    # minted. Both can change between runs, so this is a fourth composition fork rather than a
    # property of the build.
    metadata["github_guidance"] = github_guidance
    # Whether the business-knowledge section rendered — a fifth composition fork, resolved per run
    # from the team's flag + a maintained knowledge base (`_business_knowledge_maintained_for_team`).
    # Both inputs can change between runs, so like `github_guidance` this is stamped rather than
    # re-derived at read time, letting an eval or A/B compare only runs that got the same prompt.
    metadata["business_knowledge_maintained"] = business_knowledge_maintained
    # Dispatch-time snapshot of the structured-output contract. The prompt renders this exact
    # schema, so the record endpoint validates against the snapshot rather than the live config
    # value — a mid-run schema edit must not reject records that match what the run was shown.
    # Clearing the config's schema entirely still fails the channel closed mid-run (the kill
    # switch); see `tools/structured_output._resolve_schema`. Gated on `emit` like the prompt
    # section: records land solely as project events, so a dry-run scout has no channel.
    if config.structured_output_schema and config.emit:
        metadata["structured_output_schema"] = config.structured_output_schema
    return SignalScoutRun.objects.unscoped().create(
        id=run_id,
        task_run=task_run,
        team=team,
        scout_config=config,
        skill_name=skill.name,
        skill_version=skill.version,
        metadata=metadata,
    )


@dataclass(frozen=True)
class _FailureStreak:
    """Breaker state after a failed run. `tripped` is the *transition* into paused, not the
    paused state itself — a re-failed probe leaves the status where it is without tripping
    again, so the alerting event fires once per wedge rather than once per doomed run."""

    count: int
    tripped: bool
    threshold: int


def _clear_failure_streak(config_id: Any) -> None:
    """Zero the breaker after a successful run and lift its pause. Best-effort: the run
    succeeded, so a bookkeeping failure here must not turn it into a failure. The streak reset
    is filtered so the common case (a healthy lane) does no write at all; the resume goes
    through the transition helper, whose reason scoping means only the breaker's own
    `repeated_failures` pause can be lifted here — never a human's, never another writer's."""
    try:
        SignalScoutConfig.all_teams.filter(pk=config_id).exclude(consecutive_failure_count=0).update(
            consecutive_failure_count=0
        )
        config = SignalScoutConfig.all_teams.filter(pk=config_id).first()
        if (
            config is not None
            and config.status == SignalScoutConfig.Status.PAUSED_BY_SYSTEM
            and config.pause_reason == SignalScoutConfig.PauseReason.REPEATED_FAILURES
        ):
            resumed = config.transition_status_by_system(
                SignalScoutConfig.Status.ACTIVE,
                pause_reason=SignalScoutConfig.PauseReason.REPEATED_FAILURES,
            )
            if not resumed:
                # Refused resumes are legitimate (team back at its enabled-scout cap, or the
                # pause changed hands since the read) — the lane stays paused, worth a trace.
                logger.info(
                    "signals_scout: probe succeeded but resume was refused",
                    extra={"scout_config_id": str(config_id)},
                )
    except Exception:
        logger.exception("signals_scout: failed to clear failure streak", extra={"scout_config_id": str(config_id)})


def _failure_streak_runs_in_window(config: SignalScoutConfig) -> int:
    """Runs this lane's schedule fits in the breaker's tolerance window — what it scales on.

    A cron schedule takes precedence over `run_interval_minutes` at dispatch, and the column
    keeps whatever value it held before the cron was set, so reading the column alone would
    size the breaker off a cadence the lane no longer runs at.

    Cron gaps are uneven, and no single gap answers the question the breaker asks: "0,30 0 * * *"
    has a 30-minute gap but runs twice a day, so its tightest gap would buy it the tolerance of a
    lane that runs all day. So count occurrences over a whole schedule cycle and take the fullest
    window — the most failures an outage of that length can actually leave behind.

    A malformed expression can only arrive via an out-of-band write (the API validates on save);
    fall back to the rolling interval rather than fail a run's breaker bookkeeping over it.
    """
    if config.run_cron_schedule:
        try:
            return _cron_runs_in_window(config.run_cron_schedule)
        except (CroniterError, ValueError):
            logger.warning(
                "signals_scout: invalid cron schedule while sizing failure breaker",
                extra={"scout_config_id": str(config.pk)},
            )
    return interval_runs_in_tolerance_window(config.run_interval_minutes)


@lru_cache(maxsize=256)
def _cron_runs_in_window(cron_schedule: str) -> int:
    """Fullest tolerance window of occurrences (`FAILURE_STREAK_MIN_SPAN_MINUTES` plus the DST
    slack) anywhere in the schedule's sampled cycle. Cached because it is a pure function of the
    schedule string given the fixed reference, and the densest schedules cost a few hundred
    milliseconds to walk.

    Each window's count is read at its last occurrence: the occurrences within `window` looking
    back from occurrence t are exactly the ones a window opened at its earliest member covers, so
    the running deque sees every half-open window's count without materializing the sample. That
    matches `interval_runs_in_tolerance_window`'s half-open count for a lane with no cron.
    """
    iterator = croniter(cron_schedule, _CRON_WINDOW_REFERENCE)
    window = timedelta(minutes=FAILURE_STREAK_MIN_SPAN_MINUTES + _CRON_WINDOW_DST_SLACK_MINUTES)
    horizon = _CRON_WINDOW_REFERENCE + _CRON_WINDOW_HORIZON + window
    in_window: deque[datetime] = deque()
    # A schedule with no occurrence inside the horizon (e.g. February 29th) still runs once.
    fullest = 1
    for _ in range(_CRON_WINDOW_MAX_SAMPLES):
        occurrence = iterator.get_next(datetime)
        if occurrence > horizon:
            break
        while in_window and in_window[0] <= occurrence - window:
            in_window.popleft()
        in_window.append(occurrence)
        fullest = max(fullest, len(in_window))
        if fullest >= FAILURE_STREAK_MAX_RUNS:
            break
    return fullest


def _record_failure_streak(config_id: Any) -> _FailureStreak | None:
    """Bump the failure streak and pause the lane at the threshold. Returns None when the row
    is gone or the write failed — the caller only uses the result to decide whether to emit the
    auto-paused event, and a failure here must never mask the run's own error.

    The bump is an atomic `F()` increment, not read-then-write: the runner's single-flight guard
    means one run per (team, skill) at a time, but a config edit's streak reset can land
    concurrently, and a stale absolute write would resurrect the streak the edit just cleared.
    The threshold is per-lane, derived from the runs the config's own schedule fits in the
    tolerance window (`failure_streak_pause_threshold`), so the same wall-clock tolerance holds
    whether the lane runs hourly or monthly.

    The pause goes through the transition helper: `tripped` is True only when the helper actually
    moved the status, so a re-failed probe (already paused, transition is a no-op) re-arms the
    cooldown via its own `last_run_at` stamp without firing the trip event again. The error text
    rides on the events, not the row — the row records only the reason taxonomy
    (`repeated_failures`).
    """
    try:
        updated = SignalScoutConfig.all_teams.filter(pk=config_id).update(
            consecutive_failure_count=F("consecutive_failure_count") + 1
        )
        if not updated:
            return None
        config = SignalScoutConfig.all_teams.filter(pk=config_id).first()
        if config is None:
            return None
        count = config.consecutive_failure_count
        threshold = failure_streak_pause_threshold(_failure_streak_runs_in_window(config))
        tripped = False
        if count >= threshold:
            tripped = config.transition_status_by_system(
                SignalScoutConfig.Status.PAUSED_BY_SYSTEM,
                pause_reason=SignalScoutConfig.PauseReason.REPEATED_FAILURES,
            )
        return _FailureStreak(count=count, tripped=tripped, threshold=threshold)
    except Exception:
        logger.exception("signals_scout: failed to record failure streak", extra={"scout_config_id": str(config_id)})
        return None


def _poll_timeout_properties(exc: BaseException) -> dict[str, Any] | None:
    """Turn-log diagnostics for a run that died at the per-turn poll wall, or None for any other
    failure. Every wall failure raises the same error string, which is why the fleet's timeout
    rate reads as one cause; these properties split it into the populations that need different
    fixes — an agent that never emitted a single turn-relevant line (never started), one that
    worked and then went silent, and one still streaming when the budget ran out (the budget,
    not the agent, is the constraint)."""
    if not isinstance(exc, TurnPollTimeout):
        return None
    return exc.diagnostics()


def _run_row_exists(run_id: Any, team_id: int) -> bool:
    return SignalScoutRun.objects.unscoped().filter(team_id=team_id, id=run_id).exists()


def _read_run_metrics(run_id: Any, team_id: int) -> tuple[int, str | None]:
    # The bridge row carries the authoritative emit tally (the emit tool bumps it in-run)
    # and the FK to the linked TaskRun — the join key into LLM analytics, where the
    # richer per-run metrics (tool calls, generations, tokens, cost) already live. Reading
    # both here keeps that linkage on failed runs too, not just clean completions. Returns
    # (0, None) when the row never persisted (failure before the first turn).
    row = (
        SignalScoutRun.objects.unscoped()
        .filter(team_id=team_id, id=run_id)
        .values_list("emitted_count", "task_run_id")
        .first()
    )
    if row is None:
        return 0, None
    emitted_count, task_run_id = row
    return emitted_count or 0, str(task_run_id) if task_run_id else None


def _capture_run_started(
    *,
    team: Team,
    config: SignalScoutConfig,
    skill: LoadedSkill,
    github_guidance: bool,
    business_knowledge_maintained: bool,
    run_id: Any,
    task_run_id: str,
    model: str | None = None,
    runtime_adapter: str | None = None,
) -> None:
    """Emit the scout-owned run-started analytics event.

    The lifecycle counterpart to `signals_scout_run_finished`, fired once the TaskRun + bridge
    row exist and the run has cleared the reap + single-flight guards. Keyed on the team (same
    shape as the finished event) so the two join on `run_id`: `started` minus `finished` is the
    in-flight / stalled set, and a `started` with no `finished` is a run that died before
    finalize — an event-derived stall signal with no warehouse lag. Best-effort: a capture
    failure must never block the run.
    """
    properties: dict[str, Any] = {
        "skill_name": skill.name,
        "skill_version": skill.version,
        "scout_config_id": str(config.id),
        "run_id": str(run_id),
        "task_run_id": task_run_id,
    }
    _attach_run_shape_props(
        properties,
        config=config,
        skill=skill,
        github_guidance=github_guidance,
        business_knowledge_maintained=business_knowledge_maintained,
        model=model,
        runtime_adapter=runtime_adapter,
    )
    try:
        posthoganalytics.capture(
            event="signals_scout_run_started",
            distinct_id=str(team.uuid),
            properties=properties,
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture run-started analytics event",
            extra={"team_id": team.id, "run_id": str(run_id), "skill_name": skill.name},
        )


def _capture_run_reaped(
    *,
    team: Team,
    skill_name: str,
    run_id: Any,
    task_run_id: str,
    status_before: str,
    age_seconds: float,
) -> None:
    """Emit a scout-owned event when a stranded run is reaped (see `_self_heal_stale_runs`).

    A run orphaned by a hard worker death never reaches the finalize path, so it emits no
    `signals_scout_run_finished` — the reap is otherwise visible only in the logs. This event
    surfaces the strand directly: a rising count is the worker-death / mass-stall shape, and
    `status_before` + `age_seconds` distinguish a routine one-off from a fleet event. Keyed on
    the team to match the other scout lifecycle events. Best-effort: a capture failure must
    never block the reap or the new run.
    """
    try:
        posthoganalytics.capture(
            event="signals_scout_run_reaped",
            distinct_id=str(team.uuid),
            properties={
                "skill_name": skill_name,
                "run_id": str(run_id),
                "task_run_id": task_run_id,
                "status_before": status_before,
                "age_seconds": round(age_seconds, 1),
                "stale_cutoff_seconds": STALE_RUN_CUTOFF_S,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture run-reaped analytics event",
            extra={"team_id": team.id, "run_id": str(run_id), "skill_name": skill_name},
        )


def _capture_config_auto_paused(
    *,
    team: Team,
    config: SignalScoutConfig,
    skill_name: str,
    run_id: Any,
    failure_count: int,
    failure_streak_threshold: int,
    reason: str,
) -> None:
    """Emit a scout-owned event when a lane's failure-streak breaker trips.

    The state is also readable on the config row (and its API surface), but a wedge needs to be
    *noticed*, not looked up: a lane that has never once succeeded is otherwise indistinguishable
    from healthy traffic in the `signals_scout_run_finished` stream, which is why one tenant could
    fail every run for days with an empty inbox and nobody see it. Fires only on the transition, so
    a count here is a count of wedges. Best-effort: a capture failure must never affect the run.
    """
    try:
        posthoganalytics.capture(
            event="signals_scout_config_auto_paused",
            distinct_id=str(team.uuid),
            properties={
                "skill_name": skill_name,
                "scout_config_id": str(config.id),
                "run_id": str(run_id),
                "consecutive_failure_count": failure_count,
                # A wedge count is only readable next to the threshold the lane was actually
                # held to, and the threshold only next to the schedule it was derived from
                # (the cron when set, else the interval).
                "failure_streak_threshold": failure_streak_threshold,
                "run_interval_minutes": config.run_interval_minutes,
                "run_cron_schedule": config.run_cron_schedule,
                "auto_pause_reason": reason,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture config auto-paused analytics event",
            extra={"team_id": team.id, "skill_name": skill_name},
        )


def _attach_run_shape_props(
    properties: dict[str, Any],
    *,
    config: SignalScoutConfig,
    skill: LoadedSkill,
    github_guidance: bool,
    business_knowledge_maintained: bool,
    model: str | None,
    runtime_adapter: str | None,
) -> None:
    """Attach the dimensions that describe what this run was configured with, to both lifecycle
    events from one place so the started and finished streams can never drift apart.

    `harness_prompt_version` is always present: it identifies the prompt build the run was given,
    which is the dimension a prompt A/B has to hold constant, and until it existed nothing recorded
    which build a run used. Model and runtime adapter are attached only when the
    `scouts-model-selection` gate (or a runtime pin) routed the run, so their absence means the
    agent-server default served it. `network_access` follows the same absent-means-default
    convention (attached only for `full`), so an event-based readout never pools runs with
    different egress capabilities under one model or prompt. All of these make run outcomes
    (timeout rate, runtime, emit volume) sliceable without joining through $ai_generation.
    """
    properties["harness_prompt_version"] = HARNESS_PROMPT_VERSION
    properties["report_channel"] = resolve_report_channel_variant(skill.allowed_tools)
    properties["skill_origin"] = skill.origin
    properties["github_guidance"] = github_guidance
    properties["business_knowledge_maintained"] = business_knowledge_maintained
    if config.network_access == SignalScoutConfig.NetworkAccess.FULL:
        properties["network_access"] = config.network_access
    if model is not None:
        properties["model"] = model
    if runtime_adapter is not None:
        properties["runtime_adapter"] = runtime_adapter


def _capture_run_finished(
    *,
    team: Team,
    config: SignalScoutConfig,
    skill: LoadedSkill,
    github_guidance: bool,
    business_knowledge_maintained: bool,
    run_id: Any,
    task_run_id: str | None,
    status: str,
    runtime_s: float,
    emitted_count: int | None,
    model: str | None = None,
    runtime_adapter: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    extra_properties: dict[str, Any] | None = None,
) -> None:
    """Emit the scout-owned per-run analytics event.

    Complements the generic `task_run_completed` / `task_run_failed` events (which only
    differentiate scout runs by `origin_product="signals_scout"`) with the dimensions a
    scout experiment segments on: skill identity, body version, outcome, duration, and
    emit volume — keyed on the team so it joins both to the emit-side `signal_emitted`
    events and to the team-level experiment exposure. Best-effort: a capture failure must
    never fail or mask the run outcome.

    On `status='failed'`, `error_type` (the exception class) and a truncated `error_message`
    are attached so the failure rate is breakable down by cause without digging into worker
    logs — the bulk of scout failures fail in this layer before the `process-task` workflow's
    own `task_run_failed` event ever fires, so this is the only event that carries their reason.
    `extra_properties` carries cause-specific detail the error string can't (today: the turn-log
    diagnostics behind a per-turn poll timeout, which is a single string covering several
    distinct failures).
    """
    properties: dict[str, Any] = {
        "skill_name": skill.name,
        "skill_version": skill.version,
        "scout_config_id": str(config.id),
        "run_id": str(run_id),
        "task_run_id": task_run_id,
        "status": status,
        "runtime_seconds": round(runtime_s, 1),
        "emitted_count": emitted_count,
    }
    _attach_run_shape_props(
        properties,
        config=config,
        skill=skill,
        github_guidance=github_guidance,
        business_knowledge_maintained=business_knowledge_maintained,
        model=model,
        runtime_adapter=runtime_adapter,
    )
    # Only attach failure context on failed runs — keeps successful / cancelled events clean
    # rather than carrying explicit-null error fields on every event.
    if error_type is not None:
        properties["error_type"] = error_type
        properties["error_message"] = error_message
    if extra_properties:
        properties.update(extra_properties)
    try:
        posthoganalytics.capture(
            event="signals_scout_run_finished",
            distinct_id=str(team.uuid),
            properties=properties,
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture run-finished analytics event",
            extra={"team_id": team.id, "run_id": str(run_id), "skill_name": skill.name},
        )


def _finalize_run_row(*, run_id: Any, team_id: int, summary: str) -> None:
    # Targeted UPDATE rather than `.save()` — the row's other fields are untouched
    # by the agent's close-out, and `update()` skips the full model refresh.
    SignalScoutRun.objects.unscoped().filter(team_id=team_id, id=run_id).update(summary=summary)
    # Stamped here rather than at each emit/edit site so the flags are computed once, from the
    # run's settled output, in the same hop that persists the close-out. Best-effort inside, so
    # a stamp failure never costs the summary write that already landed above.
    stamp_derived_metadata(run_id=run_id, team_id=team_id)


def _step_name(skill: LoadedSkill) -> str:
    # Surfaces in the Task title and S3 log prefix. Keep terse — the sandbox truncates.
    safe = skill.name.replace(" ", "_")[:40]
    return f"signals_scout:{safe}"


def _ai_stage(skill: LoadedSkill) -> str:
    """The `ai_stage` tag every $ai_generation of this run carries.

    `scout:<skill>` so LLM-analytics cost is breakdown-able per scout while the whole fleet
    stays selectable by the `scout:` prefix. Only canonical skill *names* go in the tag — a
    custom scout's name is team-authored, so admitting it would grow the cardinality of a
    stage tag with the fleet's teams. The gate is the name, not `skill.origin`: a canonical
    scout a team has edited in place is still one named scout across the fleet.
    """
    if skill.name not in canonical_skill_names():
        return f"{SCOUT_AI_STAGE_PREFIX}custom"
    short = skill.name.removeprefix(SIGNALS_SCOUT_SKILL_PREFIX)
    return f"{SCOUT_AI_STAGE_PREFIX}{short}"
