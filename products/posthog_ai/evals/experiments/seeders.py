"""Seeders for experiments-domain sandboxed eval cases.

Each seeder is a synchronous callable that runs in a worker thread (via
``asyncio.to_thread`` from ``base.py:task()``) and creates the entities
the prompt references inside the per-case team. Returns a dict that's
exposed to scorers as ``output["seed"]`` so deterministic scorers can
reference the seeded IDs without round-tripping through ``expected``.
"""

from __future__ import annotations

import uuid
import random
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.tasks.backend.facade.agents import CustomPromptSandboxContext

logger = logging.getLogger(__name__)


__all__ = [
    "ROLLOUT_EXPERIMENT_NAME",
    "SHARED_METRIC_NAME",
    "SHARED_METRIC_EVENT",
    "UNEVEN_SPLIT_EXPERIMENT_NAME",
    "INACTIVE_FLAG_EXPERIMENT_NAME",
    "ENDED_EXPERIMENT_NAME",
    "SHIP_VARIANT_FLIP_SIGNATURE",
    "AA_TEST_EXPERIMENT_NAME",
    "AA_TEST_FLAG_KEY",
    "SeededEvent",
    "SeededVisit",
    "newcomer_events",
    "newcomer_visits",
    "seed_running_experiment",
    "seed_day_old_experiment",
    "seed_paused_and_resumed_experiment",
    "seed_shared_metric_purchase_count",
    "seed_uneven_split_experiment",
    "seed_inactive_flag_experiment",
    "seed_ended_experiment_with_flag_flip",
    "seed_newcomer_project",
    "seed_existing_user_project",
]


# Deterministic name referenced verbatim by the rollout-skill prompt so the
# agent's `experiment-list` / `experiment-get` calls can resolve the seeded
# experiment by name.
ROLLOUT_EXPERIMENT_NAME = "split test demo"
# Neutral product-flavored names — these MUST NOT hint at the diagnosis the
# agent is being asked to identify. Earlier names ("uneven split bias case",
# "stuck empty experiment") let the agent pattern-match on the experiment
# name; the rename forces the agent to actually inspect state via tools.
UNEVEN_SPLIT_EXPERIMENT_NAME = "homepage hero copy"
INACTIVE_FLAG_EXPERIMENT_NAME = "pricing page redesign"
ENDED_EXPERIMENT_NAME = "checkout cta v2"


# Verbatim description of the catch-all release condition that PostHog adds to a feature flag
# when a variant is shipped to all users, see the ship_flag_variant call in
# products.experiments.backend.experiment_service
SHIP_VARIANT_FLIP_SIGNATURE = "Added automatically when the experiment was ended to keep only one variant."


def seed_running_experiment(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed one running experiment with a 50/50 multivariate flag.

    Designed for prompts that ask the agent to change variant split on a
    *running* experiment — the canonical scenario the
    ``configuring-experiment-rollout`` skill exists to handle.

    ⚠️ SHARED SEEDER — currently used by multiple eval cases and files.
    Any change to the returned state invalidates every dependent case simultaneously.
    If you need a variant of this state for one case, add a new seeder rather than
    parameterising this one — the eval framework passes only ``context`` to seeders, so
    case-specific config has to live in the seeder definition.
    """
    from products.experiments.backend.models.experiment import Experiment
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

    team_id = context.team_id
    user_id = context.user_id

    flag = FeatureFlag.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        key=f"split-test-demo-{uuid.uuid4().hex[:6]}",
        name=f"{ROLLOUT_EXPERIMENT_NAME} flag",
        filters={
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        },
        active=True,
    )

    experiment = Experiment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=ROLLOUT_EXPERIMENT_NAME,
        description="Seeded by eval — running experiment with 50/50 split.",
        feature_flag=flag,
        start_date=datetime.now(tz=UTC) - timedelta(days=7),
        end_date=None,
    )

    payload: dict[str, Any] = {
        "experiment_id": experiment.id,
        "experiment_name": experiment.name,
        "feature_flag_id": flag.id,
        "feature_flag_key": flag.key,
        "initial_split": {"control": 50, "test": 50},
    }
    logger.info(
        "Seeded running experiment for team_id=%s: experiment_id=%s flag_key=%s",
        team_id,
        experiment.id,
        flag.key,
    )
    return payload


def _seed_split_test_experiment_started_at(
    context: CustomPromptSandboxContext, *, start_date: datetime, description: str
) -> dict[str, Any]:
    """Seed the shared 50/50 experiment with the start date that a case's prompt describes."""
    from products.experiments.backend.models.experiment import Experiment

    payload = seed_running_experiment(context)
    Experiment.objects.filter(team_id=context.team_id, id=payload["experiment_id"]).update(
        start_date=start_date, description=description
    )
    return {**payload, "start_date": start_date.isoformat()}


def seed_day_old_experiment(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed the 50/50 experiment launched one day ago, for prompts that describe a first-day read."""
    return _seed_split_test_experiment_started_at(
        context,
        start_date=datetime.now(tz=UTC) - timedelta(days=1),
        description="Seeded by eval — running experiment launched yesterday.",
    )


def seed_paused_and_resumed_experiment(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed the 50/50 experiment two weeks into its run, paused for five days in the middle and resumed.

    The pause leaves the same trace the product writes: the flag's ``active`` flip under the
    FeatureFlag scope and a ``paused`` / ``resumed`` entry under the Experiment scope, so an agent
    that reads the activity log finds the pause the prompt describes.
    """
    from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail

    now = datetime.now(tz=UTC)
    paused_at = now - timedelta(days=9)
    resumed_at = now - timedelta(days=4)

    payload = _seed_split_test_experiment_started_at(
        context,
        start_date=now - timedelta(days=14),
        description="Seeded by eval — running experiment, paused for five days and resumed.",
    )

    for created_at, activity, active_before, active_after in (
        (paused_at, "paused", True, False),
        (resumed_at, "resumed", False, True),
    ):
        ActivityLog.objects.create(
            team_id=context.team_id,
            user_id=context.user_id,
            was_impersonated=False,
            is_system=False,
            item_id=str(payload["feature_flag_id"]),
            scope="FeatureFlag",
            activity="updated",
            detail=Detail(
                name=payload["feature_flag_key"],
                changes=[
                    Change(
                        type="FeatureFlag",
                        action="changed",
                        field="active",
                        before=active_before,
                        after=active_after,
                    )
                ],
            ),
            created_at=created_at,
        )
        ActivityLog.objects.create(
            team_id=context.team_id,
            user_id=context.user_id,
            was_impersonated=False,
            is_system=False,
            item_id=str(payload["experiment_id"]),
            scope="Experiment",
            activity=activity,
            detail=Detail(name=payload["experiment_name"]),
            created_at=created_at,
        )

    return {
        **payload,
        "paused_at": paused_at.isoformat(),
        "resumed_at": resumed_at.isoformat(),
    }


def seed_uneven_split_experiment(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed a *running* experiment with an 80/20 multivariate split and the default
    ``multiple_variant_handling="exclude"``.

    Carrier scenario for diagnostic group A (bias & skew) — the agent should
    recognise that an 80/20 split combined with Exclude systematically removes
    overlap users from the smaller variant, biasing the test arm.
    """
    from products.experiments.backend.models.experiment import Experiment
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

    team_id = context.team_id
    user_id = context.user_id

    flag = FeatureFlag.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        key=f"uneven-split-{uuid.uuid4().hex[:6]}",
        name=f"{UNEVEN_SPLIT_EXPERIMENT_NAME} flag",
        filters={
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 80},
                    {"key": "test", "name": "Test", "rollout_percentage": 20},
                ]
            },
        },
        active=True,
    )

    experiment = Experiment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=UNEVEN_SPLIT_EXPERIMENT_NAME,
        description="Seeded by eval — 80/20 split, default exclude handling.",
        feature_flag=flag,
        start_date=datetime.now(tz=UTC) - timedelta(days=14),
        end_date=None,
    )

    return {
        "experiment_id": experiment.id,
        "experiment_name": experiment.name,
        "feature_flag_id": flag.id,
        "feature_flag_key": flag.key,
        "initial_split": {"control": 80, "test": 20},
    }


def seed_inactive_flag_experiment(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed a 'running' experiment whose feature flag is INACTIVE.

    Carrier scenario for diagnostic group B (empty experiment) — the agent
    should recognise that `feature_flag.active=False` means `$feature_flag_called`
    can never fire, so the exposure-shape snapshot will be empty and the
    diagnostic is B10 / A5 (flag inactive / experiment not actually live).
    """
    from products.experiments.backend.models.experiment import Experiment
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

    team_id = context.team_id
    user_id = context.user_id

    flag = FeatureFlag.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        key=f"inactive-empty-{uuid.uuid4().hex[:6]}",
        name=f"{INACTIVE_FLAG_EXPERIMENT_NAME} flag",
        filters={
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        },
        # The diagnostic signature: experiment.start_date is set so the
        # experiment looks running, but the flag is off — exposures cannot fire.
        active=False,
    )

    experiment = Experiment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=INACTIVE_FLAG_EXPERIMENT_NAME,
        description="Seeded by eval — experiment with start_date set but flag inactive.",
        feature_flag=flag,
        start_date=datetime.now(tz=UTC) - timedelta(days=3),
        end_date=None,
    )

    return {
        "experiment_id": experiment.id,
        "experiment_name": experiment.name,
        "feature_flag_id": flag.id,
        "feature_flag_key": flag.key,
        "flag_active": False,
    }


def seed_ended_experiment_with_flag_flip(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed a *stopped* experiment whose feature flag was rewritten by ship-variant.

    Carrier scenario for diagnostic group E (mid-run changes / E7) — after an
    experiment is ended via `experiment-ship-variant` in the "all users" mode,
    PostHog rewrites the flag's `multivariate.variants` rollout to 0/100
    favouring the shipped variant AND prepends a catch-all release condition
    that carries a verbatim description string ([SHIP_VARIANT_FLIP_SIGNATURE]).

    The skill's prescribed diagnostic path is to read the flag's change history
    and scan for the verbatim signature in
    ``detail.changes[].after.groups[].description``. To make that path testable,
    this seeder writes an ``ActivityLog`` row with a synthetic "filters changed"
    diff that mirrors what the production ship-variant flow emits — before-state
    is a 50/50 multivariate with one release condition; after-state is the live
    0/100 payload with the catch-all condition in front.
    """
    from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail

    from products.experiments.backend.models.experiment import Experiment
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

    team_id = context.team_id
    user_id = context.user_id

    before_filters: dict[str, Any] = {
        "groups": [{"properties": [], "rollout_percentage": 100}],
        "multivariate": {
            "variants": [
                {"key": "control", "name": "Control", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ]
        },
    }
    after_filters: dict[str, Any] = {
        "groups": [
            {"properties": [], "rollout_percentage": 100, "description": SHIP_VARIANT_FLIP_SIGNATURE},
            {"properties": [], "rollout_percentage": 100},
        ],
        # Original 50/50 split was rewritten to 0/100 by ship-variant.
        "multivariate": {
            "variants": [
                {"key": "control", "name": "Control", "rollout_percentage": 0},
                {"key": "test", "name": "Test", "rollout_percentage": 100},
            ]
        },
    }

    flag = FeatureFlag.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        key=f"ship-flip-{uuid.uuid4().hex[:6]}",
        name=f"{ENDED_EXPERIMENT_NAME} flag",
        filters=after_filters,
        active=True,
    )

    experiment = Experiment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=ENDED_EXPERIMENT_NAME,
        description="Seeded by eval — experiment ended via ship-variant; flag rewritten to 0/100.",
        feature_flag=flag,
        start_date=datetime.now(tz=UTC) - timedelta(days=30),
        end_date=datetime.now(tz=UTC) - timedelta(days=1),
    )

    # Write the synthetic ship-variant diff to the activity log so
    # `feature-flags-activity-retrieve` returns the real before/after payload
    # the skill instructs the agent to scan.
    # team_id alone satisfies the ActivityLog must-have-team-or-org check —
    # organization_id is optional and not exposed on CustomPromptSandboxContext.
    ActivityLog.objects.create(
        team_id=team_id,
        user_id=user_id,
        was_impersonated=False,
        is_system=False,
        item_id=str(flag.id),
        scope="FeatureFlag",
        activity="updated",
        detail=Detail(
            name=flag.key,
            changes=[
                Change(
                    type="FeatureFlag",
                    action="changed",
                    field="filters",
                    before=before_filters,
                    after=after_filters,
                ),
            ],
        ),
    )

    return {
        "experiment_id": experiment.id,
        "experiment_name": experiment.name,
        "feature_flag_id": flag.id,
        "feature_flag_key": flag.key,
        "final_split": {"control": 0, "test": 100},
        "signature": SHIP_VARIANT_FLIP_SIGNATURE,
    }


SHARED_METRIC_NAME = "purchase count per user"
SHARED_METRIC_EVENT = "purchase_completed"


def seed_shared_metric_purchase_count(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed one shared metric: mean count of purchase_completed per user, no filters."""
    from products.experiments.backend.models.experiment import ExperimentSavedMetric

    team_id = context.team_id
    user_id = context.user_id

    query = {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {
            "kind": "EventsNode",
            "event": SHARED_METRIC_EVENT,
            "math": "total",
        },
        "uuid": str(uuid.uuid4()),
    }

    metric = ExperimentSavedMetric.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=SHARED_METRIC_NAME,
        description="Counts purchase_completed events per user.",
        query=query,
    )

    payload: dict[str, Any] = {
        "saved_metric_id": metric.id,
        "saved_metric_name": metric.name,
        "event": SHARED_METRIC_EVENT,
        "metric_type": "mean",
        "math": "total",
    }
    logger.info(
        "Seeded shared metric for team_id=%s: id=%s name=%s event=%s",
        team_id,
        metric.id,
        metric.name,
        SHARED_METRIC_EVENT,
    )
    return payload


# Guided creation (eval_guided_creation.py). Both cases run against the Hedgebox repo that every
# sandbox clones, so the newcomer's project records hedgebox.net traffic too, just very little of it.
AA_TEST_EXPERIMENT_NAME = "Homepage A/A test"
AA_TEST_FLAG_KEY = "homepage-aa-test"
# One new visitor every three days puts about 10 in any 30-day window.
NEWCOMER_VISIT_INTERVAL_DAYS = 3
NEWCOMER_HISTORY_DAYS = 255
NEWCOMER_AA_TEST_AGE_DAYS = 250
_NEWCOMER_RANDOM_SEED = 2026_10_21
_HEDGEBOX_HOST = "hedgebox.net"
_UPLOADED_FILE_PROPERTIES: dict[str, Any] = {
    "file_type": "image/png",
    "file_size_b": 2_400_000,
    "used_mb": 2_400_000,
}


@frozen
class SeededVisit:
    distinct_id: str
    session_id: str
    started_at: datetime
    variant: Literal["control", "test"] | None
    """``None`` for visits before the A/A test started."""
    reached_signup_page: bool
    signed_up: bool
    uploaded_file: bool
    browser: str
    os: str
    device_type: str
    referring_domain: str


@frozen
class SeededEvent:
    event: str
    distinct_id: str
    timestamp: datetime
    properties: dict[str, Any]


def newcomer_visits(*, now: datetime) -> tuple[SeededVisit, ...]:
    rng = random.Random(_NEWCOMER_RANDOM_SEED)
    aa_started_at = now - timedelta(days=NEWCOMER_AA_TEST_AGE_DAYS)
    visits: list[SeededVisit] = []
    for index in range(NEWCOMER_HISTORY_DAYS // NEWCOMER_VISIT_INTERVAL_DAYS):
        days_ago = index * NEWCOMER_VISIT_INTERVAL_DAYS + rng.uniform(0.1, NEWCOMER_VISIT_INTERVAL_DAYS - 0.1)
        started_at = now - timedelta(days=days_ago)
        device_type = rng.choice(("Desktop", "Desktop", "Mobile"))
        reached_signup_page = rng.random() < 0.35
        signed_up = reached_signup_page and rng.random() < 0.6
        uploaded_file = signed_up and rng.random() < 0.6
        variant: Literal["control", "test"] = rng.choice(("control", "test"))
        visits.append(
            SeededVisit(
                distinct_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_HEDGEBOX_HOST}/visitor/{index}")),
                session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_HEDGEBOX_HOST}/session/{index}")),
                started_at=started_at,
                variant=variant if started_at >= aa_started_at else None,
                reached_signup_page=reached_signup_page,
                signed_up=signed_up,
                uploaded_file=uploaded_file,
                browser=rng.choice(("Chrome", "Safari", "Firefox")),
                os=rng.choice(("iOS", "Android")) if device_type == "Mobile" else rng.choice(("Mac OS X", "Windows")),
                device_type=device_type,
                referring_domain=rng.choice(("$direct", "$direct", "www.google.com")),
            )
        )
    return tuple(visits)


def _page_properties(path: str) -> dict[str, Any]:
    return {"$current_url": f"https://{_HEDGEBOX_HOST}{path}", "$pathname": path}


def newcomer_events(visit: SeededVisit) -> list[SeededEvent]:
    """One homepage session, in the Hedgebox taxonomy, with the A/A flag's exposure once it existed."""
    common: dict[str, Any] = {
        "$host": _HEDGEBOX_HOST,
        "$lib": "web",
        "$browser": visit.browser,
        "$os": visit.os,
        "$device_type": visit.device_type,
        "$session_id": visit.session_id,
        "$referring_domain": visit.referring_domain,
    }
    if visit.variant is not None:
        common[f"$feature/{AA_TEST_FLAG_KEY}"] = visit.variant
        common["$active_feature_flags"] = [AA_TEST_FLAG_KEY]

    events: list[SeededEvent] = []

    def add(event: str, seconds_in: int, properties: dict[str, Any]) -> None:
        events.append(
            SeededEvent(
                event=event,
                distinct_id=visit.distinct_id,
                timestamp=visit.started_at + timedelta(seconds=seconds_in),
                properties={**common, **properties},
            )
        )

    if visit.variant is not None:
        add(
            "$feature_flag_called",
            0,
            {"$feature_flag": AA_TEST_FLAG_KEY, "$feature_flag_response": visit.variant},
        )
    add("$pageview", 1, _page_properties("/"))
    last_path = "/"
    if visit.reached_signup_page:
        add("$pageview", 35, _page_properties("/signup/"))
        last_path = "/signup/"
    if visit.signed_up:
        add("signed_up", 80, {"from_invite": False})
    if visit.uploaded_file:
        add("$pageview", 95, _page_properties("/files/"))
        add("uploaded_file", 140, dict(_UPLOADED_FILE_PROPERTIES))
        last_path = "/files/"
    add("$pageleave", 170, _page_properties(last_path))
    return events


def _hide_case_labels(team_id: int, user_id: int) -> None:
    """The harness names the org and the user's email after the case, and the agent can read both."""
    from posthog.models import Organization, User

    Organization.objects.filter(team__id=team_id).update(name="Hedgebox")
    User.objects.filter(id=user_id).update(email=f"karen-{user_id}@hedgebox.example")


def _visitor_person_properties(visit: SeededVisit, index: int) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "$browser": visit.browser,
        "$os": visit.os,
        "$device_type": visit.device_type,
        "$initial_referring_domain": visit.referring_domain,
    }
    if visit.signed_up:
        properties["email"] = f"visitor-{index}@example.com"
    return properties


def seed_newcomer_project(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """A project with about 10 visitors a month and one A/A test the same user started months ago and never ended.

    Runs on an empty project (``inherit_demo_data=False``), so the seeded sample is all the data the agent sees.
    Persons go to the persons database as well as ClickHouse, because personhog serves exact person lookups
    from it.
    """
    from posthog.models import Team
    from posthog.models.event.util import bulk_create_events
    from posthog.models.person.util import create_person, create_person_distinct_id
    from posthog.persons_db import persons_db_connection
    from posthog.persons_seed import insert_seed_distinct_id, insert_seed_person

    from products.demo.backend.facade.api import infer_taxonomy_for_team
    from products.experiments.backend.models.experiment import Experiment
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

    team_id = context.team_id
    user_id = context.user_id
    _hide_case_labels(team_id, user_id)

    now = datetime.now(tz=UTC)
    visits = newcomer_visits(now=now)
    team = Team.objects.get(id=team_id)

    rows: list[dict[str, Any]] = []
    with persons_db_connection(writer=True, autocommit=True) as conn:
        for index, visit in enumerate(visits):
            person_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{team_id}:{visit.distinct_id}"))
            properties = _visitor_person_properties(visit, index)
            events = newcomer_events(visit)
            last_seen_at = events[-1].timestamp
            person_id = insert_seed_person(
                conn,
                team_id=team_id,
                properties=properties,
                is_identified=visit.signed_up,
                uuid=person_uuid,
                version=0,
                created_at=visit.started_at,
                last_seen_at=last_seen_at,
            )
            insert_seed_distinct_id(conn, team_id=team_id, person_id=person_id, distinct_id=visit.distinct_id)
            create_person(
                team_id=team_id,
                version=0,
                uuid=person_uuid,
                properties=properties,
                is_identified=visit.signed_up,
                created_at=visit.started_at,
                last_seen_at=last_seen_at,
            )
            create_person_distinct_id(team_id=team_id, distinct_id=visit.distinct_id, person_id=person_uuid)
            rows.extend(
                {
                    "event": event.event,
                    "team": team,
                    "distinct_id": event.distinct_id,
                    "timestamp": event.timestamp,
                    "properties": event.properties,
                    "person_id": person_uuid,
                    "person_properties": properties,
                }
                for event in events
            )
    bulk_create_events(rows)

    team.ingested_event = True
    team.completed_snippet_onboarding = True
    team.has_completed_onboarding_for = {**(team.has_completed_onboarding_for or {}), "product_analytics": True}
    team.save(update_fields=["ingested_event", "completed_snippet_onboarding", "has_completed_onboarding_for"])
    infer_taxonomy_for_team(team_id)

    aa_started_at = now - timedelta(days=NEWCOMER_AA_TEST_AGE_DAYS)
    flag = FeatureFlag.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        key=AA_TEST_FLAG_KEY,
        name=f"{AA_TEST_EXPERIMENT_NAME} flag",
        filters={
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        },
        active=True,
        created_at=aa_started_at - timedelta(days=1),
    )
    metric_uuid = str(uuid.uuid4())
    experiment = Experiment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=AA_TEST_EXPERIMENT_NAME,
        description="Both variants show the same homepage, to check the setup before running a real test.",
        feature_flag=flag,
        metrics=[
            {
                "kind": "ExperimentMetric",
                "metric_type": "funnel",
                "uuid": metric_uuid,
                "name": "Homepage to signup",
                "series": [
                    {"kind": "EventsNode", "event": "$pageview"},
                    {"kind": "EventsNode", "event": "signed_up"},
                ],
                "goal": "increase",
            }
        ],
        primary_metrics_ordered_uuids=[metric_uuid],
        start_date=aa_started_at,
        end_date=None,
        created_at=aa_started_at - timedelta(days=1),
    )

    visitors_last_30_days = sum(1 for visit in visits if visit.started_at >= now - timedelta(days=30))
    return {
        "team_id": team_id,
        "user_id": user_id,
        "aa_experiment_id": experiment.id,
        "aa_experiment_name": experiment.name,
        "aa_feature_flag_key": flag.key,
        "visitors_last_30_days": visitors_last_30_days,
        "visitors_total": len(visits),
        "project_summary": (
            f"A small project for the Hedgebox site: about {visitors_last_30_days} unique visitors in the last "
            f"30 days, and {len(visits)} since tracking started about {NEWCOMER_HISTORY_DAYS // 30} months ago. "
            f"Its only experiment is '{AA_TEST_EXPERIMENT_NAME}', an A/A test the same user launched about "
            f"{NEWCOMER_AA_TEST_AGE_DAYS // 30} months ago. It is still running and was never ended. "
            "The project has no test account filters."
        ),
    }


def seed_existing_user_project(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Hedgebox as copied, checked for the experiments this user has already finished."""
    from posthog.clickhouse.client import sync_execute

    from products.experiments.backend.models.experiment import Experiment

    team_id = context.team_id
    user_id = context.user_id
    _hide_case_labels(team_id, user_id)

    ended = list(
        Experiment.objects.filter(
            team_id=team_id, created_by_id=user_id, deleted=False, end_date__isnull=False
        ).values_list("name", "conclusion")
    )
    if not ended:
        raise RuntimeError("The Hedgebox copy has no ended experiments by this user, so the case would not test them")

    rows = sync_execute(
        "SELECT uniq(person_id) FROM events WHERE team_id = %(team_id)s AND event = '$pageview' "
        "AND timestamp >= now() - INTERVAL 30 DAY AND timestamp < now()",
        {"team_id": team_id},
    )
    visitors_last_30_days = int(rows[0][0]) if rows else 0
    ended_summary = "; ".join(f"'{name}' ({conclusion or 'no conclusion recorded'})" for name, conclusion in ended)
    return {
        "team_id": team_id,
        "user_id": user_id,
        "ended_experiment_count": len(ended),
        "visitors_last_30_days": visitors_last_30_days,
        "project_summary": (
            f"The Hedgebox project: about {visitors_last_30_days} unique visitors in the last 30 days. "
            f"The same user has run {len(ended)} experiments that ended: {ended_summary}. "
            "The project filters out test accounts."
        ),
    }
