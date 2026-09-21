"""Seeders for the experiment setup-inference evals.

Each scenario gives the per-case team one page with a known traffic shape: how many people see it,
how many of them are logged out, whether a server also reads the flag, and how often they convert.
The agent is asked to create an experiment on that page, and the scorers check that the created
experiment fits the shape.

Every scenario is invented from the list of properties it has to exercise. Generation is pure and
deterministic (`build_scenario_events`); `seed_*` functions write the result to ClickHouse and
Postgres inside the case team.

Hedgebox's own `$feature_flag_called` events carry no `$is_identified`, so the anonymous share the
agent can read comes only from the events seeded here. Other numbers mix in Hedgebox's people:
Hedgebox also visits `/pricing/`, `/files/` and `/account/team/`, so those pages' person counts are
higher than the seeded visitors. `signed_up`, `upgraded_plan`, `invited_team_member`,
`uploaded_file` and `shared_file_link` are Hedgebox events too, so metric baselines on them include
Hedgebox conversions. No scorer asserts on those numbers.
"""

from __future__ import annotations

import json
import uuid
import random
import logging
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen
from posthog.models.event.sql import BULK_INSERT_EVENT_SQL
from posthog.models.person.sql import INSERT_PERSON_DISTINCT_ID2, INSERT_PERSON_SQL

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

logger = logging.getLogger(__name__)

__all__ = [
    "SCENARIOS",
    "SHARED_SHARES_METRIC_NAME",
    "ScenarioEvents",
    "SeedEvent",
    "SetupScenario",
    "build_scenario_events",
    "seed_checkout_revenue",
    "seed_landing_page_anonymous",
    "seed_logged_in_team_page",
    "seed_low_traffic_page",
    "seed_pricing_crosses_login",
    "seed_pricing_server_local_evaluation",
    "seed_retention_files_page",
    "seed_shared_metric_reuse",
]

SITE = "https://hedgebox.net"
WEB_LIB = "web"
SERVER_LIB = "posthog-node"
# Seeded activity stays inside the tool's 7-day SDK window and 14-day target window.
FLAG_CALL_DAYS = 6
TARGET_DAYS = 13
SHARED_SHARES_METRIC_NAME = "File shares per user"
_ZERO_CLICKHOUSE_TIMESTAMP = "1970-01-01 00:00:00.000000"
_INSERT_BATCH_SIZE = 500
_PERSON_NAMESPACE = uuid.UUID("7b0d2f4e-8c1a-4e39-9f6b-2a5c3d7e1f90")


@frozen
class SetupScenario:
    """The traffic shape of one page. Shares are of visitors and sum to at most 1."""

    key: str
    path: str
    visitors: int
    anonymous_only_share: float
    """Visitors who never log in on this page."""
    crosses_login_share: float
    """Visitors seen on this page first logged out, then logged in."""
    conversion_event: str
    conversion_rate: float
    running_flag_key: str
    """A running flag the web SDK evaluates on this page, so the SDK profile has calls to read."""
    server_evaluates_locally: bool = False
    """A server SDK also evaluates `running_flag_key`, with local evaluation."""
    revenue: bool = False
    """Conversions carry a heavy-tailed `revenue` property."""
    returning_share: float = 0.0
    """Visitors who come back and convert again a week or more after their first visit."""
    seed: int = 0


SCENARIOS: dict[str, SetupScenario] = {
    scenario.key: scenario
    for scenario in (
        SetupScenario(
            key="landing_page_anonymous",
            path="/lp/secure-sharing/",
            visitors=600,
            anonymous_only_share=0.95,
            crosses_login_share=0.0,
            conversion_event="signed_up",
            conversion_rate=0.08,
            running_flag_key="lp-hero-video",
            seed=11,
        ),
        SetupScenario(
            key="pricing_crosses_login",
            path="/pricing/",
            visitors=500,
            anonymous_only_share=0.25,
            crosses_login_share=0.45,
            conversion_event="upgraded_plan",
            conversion_rate=0.06,
            running_flag_key="pricing-annual-toggle",
            seed=12,
        ),
        SetupScenario(
            key="pricing_server_local_evaluation",
            path="/pricing/",
            visitors=500,
            anonymous_only_share=0.25,
            crosses_login_share=0.45,
            conversion_event="upgraded_plan",
            conversion_rate=0.06,
            running_flag_key="pricing-annual-toggle",
            server_evaluates_locally=True,
            seed=13,
        ),
        SetupScenario(
            key="logged_in_team_page",
            path="/account/team/",
            visitors=400,
            anonymous_only_share=0.0,
            crosses_login_share=0.0,
            conversion_event="invited_team_member",
            conversion_rate=0.15,
            running_flag_key="team-roles-beta",
            seed=14,
        ),
        SetupScenario(
            key="checkout_revenue",
            path="/account/billing/checkout/",
            visitors=450,
            anonymous_only_share=0.0,
            crosses_login_share=0.0,
            conversion_event="checkout_completed",
            conversion_rate=0.35,
            running_flag_key="checkout-trust-badges",
            revenue=True,
            seed=15,
        ),
        SetupScenario(
            key="retention_files_page",
            path="/files/",
            visitors=500,
            anonymous_only_share=0.0,
            crosses_login_share=0.0,
            conversion_event="uploaded_file",
            conversion_rate=0.6,
            running_flag_key="files-grid-view",
            returning_share=0.3,
            seed=16,
        ),
        SetupScenario(
            key="low_traffic_page",
            path="/enterprise/",
            visitors=390,
            anonymous_only_share=0.95,
            crosses_login_share=0.0,
            conversion_event="requested_demo",
            conversion_rate=0.02,
            running_flag_key="enterprise-logos",
            seed=17,
        ),
        SetupScenario(
            key="shared_metric_reuse",
            path="/files/",
            visitors=450,
            anonymous_only_share=0.0,
            crosses_login_share=0.0,
            conversion_event="shared_file_link",
            conversion_rate=0.25,
            running_flag_key="files-grid-view",
            seed=18,
        ),
    )
}


@frozen
class SeedPerson:
    person_id: str
    distinct_ids: tuple[str, ...]
    identified: bool


@frozen
class SeedEvent:
    event: str
    distinct_id: str
    person_id: str
    timestamp: datetime
    properties: dict[str, Any]


@frozen
class ScenarioEvents:
    persons: tuple[SeedPerson, ...]
    events: tuple[SeedEvent, ...]


def _person_id(scenario: SetupScenario, index: int) -> str:
    return str(uuid.uuid5(_PERSON_NAMESPACE, f"{scenario.key}-{index}"))


def _revenue(rng: random.Random) -> float:
    # Most orders are a single seat; a few team plans are two orders of magnitude larger.
    if rng.random() < 0.03:
        return round(rng.uniform(1_500, 6_000), 2)
    return round(rng.lognormvariate(3.0, 0.5), 2)


def _web_properties(
    *, url: str, device_id: str, identified: bool, session_id: str, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "$lib": WEB_LIB,
        "$lib_version": "1.300.0",
        "$current_url": url,
        "$host": "hedgebox.net",
        "$pathname": url.removeprefix(SITE),
        "$device_id": device_id,
        "$is_identified": identified,
        "$session_id": session_id,
        **(extra or {}),
    }


def build_scenario_events(scenario: SetupScenario, now: datetime) -> ScenarioEvents:
    """Generate the persons and events for one scenario. Deterministic for a given `now`."""
    rng = random.Random(scenario.seed)
    url = f"{SITE}{scenario.path}"
    persons: list[SeedPerson] = []
    events: list[SeedEvent] = []

    def emit(event: str, distinct_id: str, person_id: str, at: datetime, properties: dict[str, Any]) -> None:
        if at < now:
            events.append(
                SeedEvent(
                    event=event, distinct_id=distinct_id, person_id=person_id, timestamp=at, properties=properties
                )
            )

    for index in range(scenario.visitors):
        person_id = _person_id(scenario, index)
        device_id = str(uuid.UUID(int=rng.getrandbits(128)))
        user_id = f"user-{scenario.key}-{index}@example.com"
        roll = rng.random()
        if roll < scenario.anonymous_only_share:
            visits = [(device_id, False)]
        elif roll < scenario.anonymous_only_share + scenario.crosses_login_share:
            visits = [(device_id, False), (user_id, True)]
        else:
            visits = [(user_id, True)]
        identified = visits[-1][1]
        persons.append(
            SeedPerson(
                person_id=person_id,
                distinct_ids=tuple(distinct_id for distinct_id, _ in visits),
                identified=identified,
            )
        )

        first_seen = now - timedelta(days=rng.uniform(0.2, TARGET_DAYS), minutes=rng.randint(0, 59))
        for visit_index, (distinct_id, is_identified) in enumerate(visits):
            session_id = str(uuid.UUID(int=rng.getrandbits(128)))
            visit_at = first_seen + timedelta(minutes=12 * visit_index)
            properties = _web_properties(url=url, device_id=device_id, identified=is_identified, session_id=session_id)
            emit("$pageview", distinct_id, person_id, visit_at, properties)
            if now - visit_at > timedelta(days=FLAG_CALL_DAYS):
                continue
            flag_call = {"$feature_flag": scenario.running_flag_key}
            emit(
                "$feature_flag_called",
                distinct_id,
                person_id,
                visit_at - timedelta(seconds=2),
                {**properties, **flag_call, "$feature_flag_response": rng.choice(("control", "test"))},
            )
            if scenario.server_evaluates_locally and is_identified:
                emit(
                    "$feature_flag_called",
                    distinct_id,
                    person_id,
                    visit_at - timedelta(seconds=3),
                    {
                        "$lib": SERVER_LIB,
                        "$lib_version": "5.8.0",
                        **flag_call,
                        "$feature_flag_response": rng.choice(("control", "test")),
                        "locally_evaluated": True,
                    },
                )

        converter_distinct_id, converter_identified = visits[-1]
        conversion_properties = _web_properties(
            url=url,
            device_id=device_id,
            identified=converter_identified,
            session_id=str(uuid.UUID(int=rng.getrandbits(128))),
        )
        if rng.random() < scenario.conversion_rate:
            extra = {"revenue": _revenue(rng), "currency": "USD"} if scenario.revenue else {}
            converted_at = first_seen + timedelta(minutes=12 * len(visits) + rng.randint(1, 30))
            emit(
                scenario.conversion_event,
                converter_distinct_id,
                person_id,
                converted_at,
                {**conversion_properties, **extra},
            )
        if scenario.returning_share and rng.random() < scenario.returning_share:
            returned_at = first_seen + timedelta(days=rng.uniform(7, 12))
            emit("$pageview", converter_distinct_id, person_id, returned_at, conversion_properties)
            emit(
                scenario.conversion_event,
                converter_distinct_id,
                person_id,
                returned_at + timedelta(minutes=4),
                conversion_properties,
            )

    return ScenarioEvents(persons=tuple(persons), events=tuple(events))


def _batches(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _clickhouse_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _insert_persons(team_id: int, persons: Sequence[SeedPerson], now: datetime) -> None:
    created_at = _clickhouse_timestamp(now - timedelta(days=TARGET_DAYS + 1))
    for person in persons:
        sync_execute(
            INSERT_PERSON_SQL,
            {
                "id": person.person_id,
                "created_at": created_at,
                "team_id": team_id,
                "properties": json.dumps({"email": person.distinct_ids[-1]} if person.identified else {}),
                "is_identified": int(person.identified),
                "_timestamp": now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                "is_deleted": 0,
                "version": 1,
                "last_seen_at": created_at,
            },
        )
        for distinct_id in person.distinct_ids:
            sync_execute(
                INSERT_PERSON_DISTINCT_ID2,
                {
                    "distinct_id": distinct_id,
                    "person_id": person.person_id,
                    "team_id": team_id,
                    "is_deleted": 0,
                    "version": 1,
                },
            )


def _insert_events(team_id: int, events: Sequence[SeedEvent]) -> None:
    for batch in _batches(events, _INSERT_BATCH_SIZE):
        rows: list[str] = []
        params: dict[str, Any] = {}
        for index, event in enumerate(batch):
            timestamp = _clickhouse_timestamp(event.timestamp)
            row = {
                "uuid": str(uuid.uuid4()),
                "event": event.event,
                "properties": json.dumps(event.properties),
                "timestamp": timestamp,
                "team_id": team_id,
                "distinct_id": event.distinct_id,
                "elements_chain": "",
                "person_id": event.person_id,
                "person_properties": "{}",
                "person_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
                **{f"group{group}_properties": "{}" for group in range(5)},
                **{f"group{group}_created_at": _ZERO_CLICKHOUSE_TIMESTAMP for group in range(5)},
                "person_mode": "full",
                "created_at": timestamp,
                "_timestamp": timestamp,
            }
            rows.append("(" + ", ".join(f"%({key}_{index})s" for key in row) + ", 0)")
            params.update({f"{key}_{index}": value for key, value in row.items()})
        sync_execute(BULK_INSERT_EVENT_SQL() + ", ".join(rows), params, flush=False)


def _create_running_flag(team_id: int, user_id: int, key: str) -> None:
    FeatureFlag.objects.get_or_create(
        team_id=team_id,
        key=key,
        defaults={
            "created_by_id": user_id,
            "name": key.replace("-", " "),
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
            "active": True,
        },
    )


def _seed_scenario(context: CustomPromptSandboxContext, key: str) -> dict[str, Any]:
    """Write one scenario to the case team. Call it after any other seeded rows, because the ids
    it returns mark everything that exists before the agent runs."""
    scenario = SCENARIOS[key]
    now = datetime.now(tz=UTC)
    generated = build_scenario_events(scenario, now)
    _insert_persons(context.team_id, generated.persons, now)
    _insert_events(context.team_id, generated.events)
    _create_running_flag(context.team_id, context.user_id, scenario.running_flag_key)
    logger.info(
        "Seeded setup scenario %s for team_id=%s: %d persons, %d events",
        key,
        context.team_id,
        len(generated.persons),
        len(generated.events),
    )
    return {
        "team_id": context.team_id,
        "scenario": key,
        "target_path": scenario.path,
        "conversion_event": scenario.conversion_event,
        "preexisting_experiment_ids": list(
            Experiment.objects.filter(team_id=context.team_id).values_list("id", flat=True)
        ),
        "preexisting_flag_ids": list(FeatureFlag.objects.filter(team_id=context.team_id).values_list("id", flat=True)),
    }


def seed_landing_page_anonymous(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _seed_scenario(context, "landing_page_anonymous")


def seed_pricing_crosses_login(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _seed_scenario(context, "pricing_crosses_login")


def seed_pricing_server_local_evaluation(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _seed_scenario(context, "pricing_server_local_evaluation")


def seed_logged_in_team_page(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _seed_scenario(context, "logged_in_team_page")


def seed_checkout_revenue(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _seed_scenario(context, "checkout_revenue")


def seed_retention_files_page(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _seed_scenario(context, "retention_files_page")


def seed_low_traffic_page(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _seed_scenario(context, "low_traffic_page")


def seed_shared_metric_reuse(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """The files-page scenario, plus a shared metric on the conversion event that three ended
    experiments already use as their primary metric, and one unrelated shared metric."""
    scenario = SCENARIOS["shared_metric_reuse"]
    team_id, user_id = context.team_id, context.user_id
    now = datetime.now(tz=UTC)

    def saved_metric(name: str, event: str) -> ExperimentSavedMetric:
        return ExperimentSavedMetric.objects.create(
            team_id=team_id,
            created_by_id=user_id,
            name=name,
            description=f"Counts {event} events per user.",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": event, "math": "total"},
                "uuid": str(uuid.uuid4()),
            },
        )

    shares_metric = saved_metric(SHARED_SHARES_METRIC_NAME, scenario.conversion_event)
    saved_metric("Downloads per user", "downloaded_file")

    for index, name in enumerate(("Share dialog copy", "Share button placement", "Link expiry default")):
        flag = FeatureFlag.objects.create(
            team_id=team_id,
            created_by_id=user_id,
            key=f"share-test-{index + 1}",
            name=name,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
            active=False,
        )
        experiment = Experiment.objects.create(
            team_id=team_id,
            created_by_id=user_id,
            name=name,
            feature_flag=flag,
            start_date=now - timedelta(days=90 - 25 * index),
            end_date=now - timedelta(days=70 - 25 * index),
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment, saved_metric=shares_metric, metadata={"type": "primary"}
        )

    return _seed_scenario(context, scenario.key) | {"shared_metric_id": shares_metric.id}
