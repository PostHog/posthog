"""Rotating cohorts for the workflow ideas scout.

The scout costs money on every run, and its ideas only pay back on a project that goes on to send
through Workflows at volume. So it runs on a small cohort of the projects most likely to adopt, for
a fixed trial, and the cohort then rotates. A project that tried it once waits out a cooldown before
it can be picked again, so every cohort reaches new projects.

Selection reads three adoption signals: the project already sends through another messaging tool,
it has many people with an email address, and it records revenue events. Every pick, and what the project did during its trial, is kept on a
`WorkflowIdeaTrial` row.
"""

import re
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.api.app_metrics2 import fetch_app_metric_daily_totals_by_team
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.ph_client import ph_scoped_capture

from products.cdp.backend.facade.api import enabled_destination_templates
from products.signals.backend.facade.api import enroll_scout_for_source, withdraw_scout_for_source
from products.workflows.backend.models import HogFlow, WorkflowIdeaTrial

logger = structlog.get_logger(__name__)

SCOUT_SKILL_NAME = "signals-scout-workflow-ideas"
SOURCE_PRODUCT = "workflows"
# Arbitrary, fixed key for the Postgres advisory lock that keeps two rotations from running at once.
_ROTATION_LOCK_KEY = 7_203_118_442
COHORTS_FLAG = "workflow-ideas-cohorts"
COHORTS_FLAG_DISTINCT_ID = "workflow-ideas-cohorts-discovery"

TRIAL_STARTED_EVENT = "workflow_idea_trial_started"
TRIAL_ENDED_EVENT = "workflow_idea_trial_ended"

# The messaging tools a project can already send through from PostHog. Paying for one is the
# strongest sign a project would send through Workflows instead.
_MESSAGING_TEMPLATE_RE = (
    "(customerio|customer-io|loops|braze|mailchimp|klaviyo|iterable|brevo|sendgrid|resend|mailgun|postmark"
    "|intercom|onesignal|mailjet|convertkit|beehiiv|hubspot|activecampaign|plunk|knock|courier|novu)"
)
_REVENUE_EVENT_RE = "(purchase|order_completed|order completed|checkout|subscri|trial|payment|paid|upgrade|invoice)"
_ACTIVATION_EVENT_RE = "(sign_?up|signed_?up|registered|onboarding|activated)"
_NON_PRODUCTION_RE = re.compile(r"(test|staging|stage|\bdev\b|demo|sandbox|local|\bqa\b|preview)", re.IGNORECASE)


@frozen
class CohortSettings:
    enabled: bool
    cohort_size: int
    trial_days: int
    cooldown_days: int
    run_interval_minutes: int
    min_emailable_daily_people: int
    max_billable_invocations_30d: int
    min_active_members_14d: int
    # Pins the scout's model for every enrolled project, so a cohort's cost does not depend on the fleet's model mix.
    model: str | None = None


DEFAULT_SETTINGS = CohortSettings(
    enabled=False,
    cohort_size=18,
    trial_days=14,
    cooldown_days=90,
    run_interval_minutes=3 * 24 * 60,
    min_emailable_daily_people=1000,
    max_billable_invocations_30d=10_000,
    min_active_members_14d=2,
)


@frozen
class Candidate:
    team_id: int
    segment: WorkflowIdeaTrial.Segment
    score: float
    selection: dict[str, Any]


@frozen
class RotationResult:
    ended: int
    started: int
    cohort: int | None


def read_cohort_settings() -> CohortSettings:
    """The `workflow-ideas-cohorts` flag payload over the defaults.

    The payload's `enabled` is the switch, not the flag's rollout: the payload is read with
    `match_value=True`, so it is served even when the flag evaluates off. Off unless the payload says
    `"enabled": true`, and setting it to false ends every running trial on the next rotation.
    """
    try:
        payload = posthoganalytics.get_feature_flag_payload(COHORTS_FLAG, COHORTS_FLAG_DISTINCT_ID, match_value=True)
        if isinstance(payload, str):
            payload = json.loads(payload)
    except Exception as error:
        capture_exception(error)
        payload = None
    if not isinstance(payload, dict):
        return DEFAULT_SETTINGS

    def positive_int(key: str, default: int) -> int:
        value = payload.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default

    return CohortSettings(
        enabled=payload.get("enabled") is True,
        cohort_size=positive_int("cohort_size", DEFAULT_SETTINGS.cohort_size),
        trial_days=positive_int("trial_days", DEFAULT_SETTINGS.trial_days),
        cooldown_days=positive_int("cooldown_days", DEFAULT_SETTINGS.cooldown_days),
        run_interval_minutes=positive_int("run_interval_minutes", DEFAULT_SETTINGS.run_interval_minutes),
        min_emailable_daily_people=positive_int(
            "min_emailable_daily_people", DEFAULT_SETTINGS.min_emailable_daily_people
        ),
        max_billable_invocations_30d=positive_int(
            "max_billable_invocations_30d", DEFAULT_SETTINGS.max_billable_invocations_30d
        ),
        min_active_members_14d=positive_int("min_active_members_14d", DEFAULT_SETTINGS.min_active_members_14d),
        model=payload.get("model") if isinstance(payload.get("model"), str) and payload.get("model") else None,
    )


def rotate_idea_cohort(*, settings: CohortSettings | None = None, now: datetime | None = None) -> RotationResult:
    """End the trials that are due, and start the next cohort once none is running.

    With the payload's `enabled` off, every running trial ends now. A rotation already in progress
    elsewhere makes this one a no-op, so two never pick the same cohort.
    """
    settings = settings or read_cohort_settings()
    now = now or timezone.now()

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [_ROTATION_LOCK_KEY])
        if not cursor.fetchone()[0]:
            return RotationResult(ended=0, started=0, cohort=None)
    try:
        return _rotate(settings, now)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [_ROTATION_LOCK_KEY])


def _rotate(settings: CohortSettings, now: datetime) -> RotationResult:
    running = WorkflowIdeaTrial.objects.unscoped().filter(outcome=WorkflowIdeaTrial.Outcome.RUNNING)
    ended = 0
    for trial in list(running if not settings.enabled else running.filter(ends_at__lte=now)):
        # One failing trial must not hold the rest back. It stays running with its scout, and the next rotation retries it.
        try:
            end_trial(trial, now=now)
            ended += 1
        except Exception as error:
            capture_exception(error)

    if not settings.enabled or running.exists():
        return RotationResult(ended=ended, started=0, cohort=None)

    cohort = (
        WorkflowIdeaTrial.objects.unscoped().order_by("-cohort").values_list("cohort", flat=True).first() or 0
    ) + 1
    started = 0
    for candidate in select_candidates(settings, exclude_team_ids=_teams_in_cooldown(settings, now)):
        if start_trial(candidate, cohort=cohort, settings=settings, now=now):
            started += 1
    logger.info("workflow_idea_cohort_started", cohort=cohort, teams=started, ended=ended)
    return RotationResult(ended=ended, started=started, cohort=cohort)


def start_trial(candidate: Candidate, *, cohort: int, settings: CohortSettings, now: datetime) -> bool:
    team = Team.objects.select_related("organization").get(id=candidate.team_id)
    # One transaction, so a scout is never left enabled without the trial that ends it.
    with transaction.atomic():
        enrolled = enroll_scout_for_source(
            team=team,
            skill_name=SCOUT_SKILL_NAME,
            source_product=SOURCE_PRODUCT,
            source_id=f"cohort:{cohort}",
            run_interval_minutes=settings.run_interval_minutes,
            model=settings.model,
        )
        trial = WorkflowIdeaTrial.objects.unscoped().create(
            team_id=team.id,
            cohort=cohort,
            segment=candidate.segment,
            score=candidate.score,
            selection=candidate.selection,
            started_at=now,
            ends_at=now + timedelta(days=settings.trial_days),
            ended_at=None if enrolled else now,
            outcome=WorkflowIdeaTrial.Outcome.RUNNING if enrolled else WorkflowIdeaTrial.Outcome.NOT_ENROLLED,
        )
    _capture(TRIAL_STARTED_EVENT, team, trial)
    return enrolled


def end_trial(trial: WorkflowIdeaTrial, *, now: datetime) -> None:
    """Stop the scout on this project and record what the project did with Workflows during the trial.

    Every read happens before any write, and the writes share one transaction, so a failed read leaves
    the trial running with its scout and the next rotation retries it.
    """
    environments = list(
        Team.objects.filter(Q(id=trial.team_id) | Q(parent_team_id=trial.team_id)).values_list("id", flat=True)
    )
    window = {"after": trial.started_at, "before": now}
    created_ids = set(
        HogFlow.objects.filter(
            team_id__in=environments, created_at__gte=window["after"], created_at__lte=window["before"]
        ).values_list("id", flat=True)
    )
    launched_ids = _workflows_launched(environments, **window)
    billable = sum(_billable_invocations_by_team(environments, **window).values())
    if launched_ids:
        outcome = WorkflowIdeaTrial.Outcome.ADOPTED
    elif created_ids:
        outcome = WorkflowIdeaTrial.Outcome.DRAFTED
    else:
        outcome = WorkflowIdeaTrial.Outcome.NO_CHANGE
    with transaction.atomic():
        withdraw_scout_for_source(team_id=trial.team_id, skill_name=SCOUT_SKILL_NAME, source_product=SOURCE_PRODUCT)
        trial.ended_at = now
        trial.outcome = outcome
        trial.workflows_created = len(created_ids)
        trial.workflows_launched = len(launched_ids)
        trial.billable_invocations = billable
        trial.save(
            update_fields=["ended_at", "outcome", "workflows_created", "workflows_launched", "billable_invocations"]
        )
    _capture(TRIAL_ENDED_EVENT, Team.objects.select_related("organization").get(id=trial.team_id), trial)


def select_candidates(settings: CohortSettings, *, exclude_team_ids: set[int]) -> list[Candidate]:
    """Score every project that clears the hard filters, then take a cohort balanced across segments."""
    # Scouts belong to a project's main environment, so environments count toward their project.
    by_environment = _emailable_daily_people(settings.min_emailable_daily_people)
    project_of = dict(Team.objects.filter(id__in=list(by_environment)).values_list("id", "parent_team_id"))
    emailable: dict[int, int] = defaultdict(int)
    for environment_id, people in by_environment.items():
        emailable[project_of.get(environment_id) or environment_id] += people
    team_ids = [team_id for team_id in emailable if team_id not in exclude_team_ids]
    if not team_ids:
        return []
    environments = dict(
        Team.objects.filter(Q(id__in=team_ids) | Q(parent_team_id__in=team_ids)).values_list("id", "parent_team_id")
    )
    billable: dict[int, int] = defaultdict(int)
    for environment_id, count in _billable_invocations_by_team(
        list(environments), after=timezone.now() - timedelta(days=30)
    ).items():
        billable[environments.get(environment_id) or environment_id] += count
    team_ids = [team_id for team_id in team_ids if billable.get(team_id, 0) < settings.max_billable_invocations_30d]
    features = _postgres_features(team_ids)

    scored: list[Candidate] = []
    for team_id in team_ids:
        feature = features.get(team_id)
        if (
            feature is None
            or not feature["ai_approved"]
            or feature["active_members_14d"] < settings.min_active_members_14d
        ):
            continue
        if _NON_PRODUCTION_RE.search(f"{feature['team_name']} {feature['org_name']}"):
            continue
        segment = _segment(feature, emailable[team_id])
        if segment is None:
            continue
        score = _score(feature, emailable[team_id], segment)
        scored.append(
            Candidate(
                team_id=team_id,
                segment=segment,
                score=score,
                selection={
                    "emailable_daily_people": emailable[team_id],
                    "billable_invocations_30d": billable.get(team_id, 0),
                    **{key: value for key, value in feature.items() if key not in ("team_name", "org_name")},
                },
            )
        )
    return _balanced_cohort(scored, settings.cohort_size)


def _segment(feature: dict[str, Any], emailable: int) -> WorkflowIdeaTrial.Segment | None:
    if feature["messaging_tools"] and feature["flows_active"] == 0:
        return WorkflowIdeaTrial.Segment.COMPETITOR
    if feature["flows_ever"] or feature["email_integrations"]:
        return WorkflowIdeaTrial.Segment.STALLED
    if emailable >= 5000 and feature["revenue_events"] and feature["activation_events"]:
        return WorkflowIdeaTrial.Segment.GREENFIELD
    return None


def _score(feature: dict[str, Any], emailable: int, segment: WorkflowIdeaTrial.Segment) -> float:
    # Another messaging tool counts double: a project paying for one already sends at volume.
    segment_weight = {
        WorkflowIdeaTrial.Segment.STALLED: 1.4,
        WorkflowIdeaTrial.Segment.COMPETITOR: 1.3,
        WorkflowIdeaTrial.Segment.GREENFIELD: 1.0,
    }[segment]
    revenue = 1 + min(feature["revenue_events"], 20) / 20
    competitor = 2.0 if feature["messaging_tools"] else 1.0
    return round(math.log10(max(emailable, 10)) * revenue * competitor * segment_weight, 3)


def _balanced_cohort(scored: list[Candidate], size: int) -> list[Candidate]:
    """An even share per segment, best first, with any shortfall filled by the best of the rest."""
    by_segment: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in sorted(scored, key=lambda c: -c.score):
        by_segment[candidate.segment].append(candidate)
    share = size // len(WorkflowIdeaTrial.Segment)
    picked = [c for segment in WorkflowIdeaTrial.Segment for c in by_segment[segment][:share]]
    taken = {c.team_id for c in picked}
    rest = [c for c in sorted(scored, key=lambda c: -c.score) if c.team_id not in taken]
    return picked + rest[: size - len(picked)]


def _teams_in_cooldown(settings: CohortSettings, now: datetime) -> set[int]:
    """Projects that had a trial within the cooldown, plus every project a trial converted."""
    recent = WorkflowIdeaTrial.objects.unscoped().filter(started_at__gte=now - timedelta(days=settings.cooldown_days))
    adopted = WorkflowIdeaTrial.objects.unscoped().filter(outcome=WorkflowIdeaTrial.Outcome.ADOPTED)
    return set(recent.values_list("team_id", flat=True)) | set(adopted.values_list("team_id", flat=True))


def _emailable_daily_people(minimum: int) -> dict[int, int]:
    """People with an email address seen in the last day, per project, for projects above `minimum`."""
    with tags_context(product=Product.WORKFLOWS, feature=Feature.ENRICHMENT):
        rows = sync_execute(
            """
            SELECT team_id, uniqIf(person_id, JSONExtractString(person_properties, 'email') != '') AS emailable
            FROM events
            WHERE timestamp > now() - INTERVAL 1 DAY AND timestamp <= now()
            GROUP BY team_id
            HAVING emailable >= %(minimum)s
            ORDER BY emailable DESC
            LIMIT 3000
            """,
            {"minimum": minimum},
            workload=Workload.OFFLINE,
        )
    return {int(team_id): int(emailable) for team_id, emailable in rows}


def _billable_invocations_by_team(
    team_ids: list[int], *, after: datetime, before: datetime | None = None
) -> dict[int, int]:
    with tags_context(product=Product.WORKFLOWS, feature=Feature.ENRICHMENT):
        daily = fetch_app_metric_daily_totals_by_team(
            app_source="hog_flow",
            name=["billable_invocation"],
            after=after,
            before=before,
            team_ids=team_ids,
            workload=Workload.OFFLINE,
        )
    return {
        team_id: sum(counts.get("billable_invocation", 0) for counts in days.values())
        for team_id, days in daily.items()
    }


def _workflows_launched(environments: list[int], *, after: datetime, before: datetime) -> set[str]:
    """Workflows switched live during the window, whenever they were created.

    A status change is not a new version, so the activity log is the only record of when a draft went
    live. A workflow created already live in the window counts too.
    """
    switched_live = ActivityLog.objects.filter(
        team_id__in=environments,
        scope="HogFlow",
        created_at__gte=after,
        created_at__lte=before,
        detail__changes__contains=[{"field": "status", "after": HogFlow.State.ACTIVE}],
    ).values_list("item_id", flat=True)
    created_live = HogFlow.objects.filter(
        team_id__in=environments, created_at__gte=after, created_at__lte=before, status=HogFlow.State.ACTIVE
    ).values_list("id", flat=True)
    return {str(item_id) for item_id in switched_live if item_id} | {str(flow_id) for flow_id in created_live}


def _postgres_features(team_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Adoption signals per project, read in one round trip.

    Raw SQL because the signals live in tables owned by several products (event definitions,
    integrations) and are only ever aggregated here, across projects. Each count covers the project
    and its environments.
    """
    query = f"""
        WITH ids AS (SELECT unnest(%(team_ids)s::int[]) AS team_id),
        envs AS (SELECT ids.team_id AS project_id, e.id AS env_id FROM ids JOIN posthog_team e ON e.id = ids.team_id OR e.parent_team_id = ids.team_id)
        SELECT
            t.id,
            t.name,
            o.name,
            o.is_ai_data_processing_approved IS TRUE,
            (SELECT count(*) FROM posthog_organizationmembership m JOIN posthog_user u ON u.id = m.user_id
               WHERE m.organization_id = o.id AND u.last_login > now() - interval '14 days'),
            (SELECT count(*) FROM posthog_hogflow h WHERE h.team_id IN (SELECT env_id FROM envs WHERE project_id = t.id)),
            (SELECT count(*) FROM posthog_hogflow h WHERE h.team_id IN (SELECT env_id FROM envs WHERE project_id = t.id) AND h.status = 'active'),
            (SELECT count(*) FROM posthog_integration i WHERE i.team_id IN (SELECT env_id FROM envs WHERE project_id = t.id) AND i.kind = 'email'),
            (SELECT count(*) FROM posthog_eventdefinition d WHERE d.team_id IN (SELECT env_id FROM envs WHERE project_id = t.id)
               AND d.last_seen_at > now() - interval '14 days' AND d.name ~* %(revenue_re)s),
            (SELECT count(*) FROM posthog_eventdefinition d WHERE d.team_id IN (SELECT env_id FROM envs WHERE project_id = t.id)
               AND d.last_seen_at > now() - interval '14 days' AND d.name ~* %(activation_re)s)
        FROM ids JOIN posthog_team t ON t.id = ids.team_id JOIN posthog_organization o ON o.id = t.organization_id
    """
    params: dict[str, Any] = {
        "team_ids": team_ids,
        "revenue_re": _REVENUE_EVENT_RE,
        "activation_re": _ACTIVATION_EVENT_RE,
    }
    environments = dict(
        Team.objects.filter(Q(id__in=team_ids) | Q(parent_team_id__in=team_ids)).values_list("id", "parent_team_id")
    )
    tools: dict[int, set[str]] = defaultdict(set)
    for environment_id, templates in enabled_destination_templates(list(environments), _MESSAGING_TEMPLATE_RE).items():
        tools[environments.get(environment_id) or environment_id].update(templates)
    features: dict[int, dict[str, Any]] = {}
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        for row in cursor.fetchall():
            (
                team_id,
                team_name,
                org_name,
                ai_approved,
                active,
                flows_ever,
                flows_active,
                emails,
                revenue,
                activation,
            ) = row
            features[int(team_id)] = {
                "team_name": team_name or "",
                "org_name": org_name or "",
                "ai_approved": bool(ai_approved),
                "active_members_14d": int(active),
                "flows_ever": int(flows_ever),
                "flows_active": int(flows_active),
                "messaging_tools": sorted(tools.get(int(team_id), set())),
                "email_integrations": int(emails),
                "revenue_events": int(revenue),
                "activation_events": int(activation),
            }
    return features


def _capture(event: str, team: Team, trial: WorkflowIdeaTrial) -> None:
    properties = {
        "team_id": trial.team_id,
        "cohort": trial.cohort,
        "segment": trial.segment,
        "score": trial.score,
        "outcome": trial.outcome,
        "workflows_created": trial.workflows_created,
        "workflows_launched": trial.workflows_launched,
        "billable_invocations": trial.billable_invocations,
        **{f"selection_{key}": value for key, value in (trial.selection or {}).items()},
    }
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(team.uuid),
            event=event,
            properties=properties,
            groups=groups(team.organization, team),
        )
