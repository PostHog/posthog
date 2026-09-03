"""Seeder hooks for the notebook eval cases.

The seeder contract takes no per-case parameters, so each seeded state gets its own
function. Every one of them returns ``team_id``: it is the only channel a scorer has
for reaching the case's own team, and the notebook scorers grade the documents and run
rows the agent left there rather than what the transcript claims.

Seeders run synchronously in the case's freshly cloned team, so they can write straight
to ClickHouse with the same ``TEST=1`` helpers the pytest suites use.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from django.utils import timezone

from posthog.models import Team
from posthog.models.event.util import bulk_create_events
from posthog.models.person.util import create_person, create_person_distinct_id

from products.notebooks.evals.synthesizer import CHURN_TOKEN, SIGNUP_EVENT, ChurnAccount, build_churn_needle
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

# Realistic props for the planted file events, so a churn query that groups or filters on
# file properties still sees well-formed rows. Fixed values keep the seed deterministic.
_FILE_EVENT_PROPS: dict[str, dict[str, Any]] = {
    "uploaded_file": {"file_type": "application/pdf", "file_size_b": 5_242_880, "used_mb": 5_242_880},
    "downloaded_file": {"file_type": "application/pdf", "file_size_b": 5_242_880, "file_name": "quarterly-report"},
    "shared_file_link": {"file_type": "application/pdf", "file_size_b": 5_242_880},
}


def seed_case_team(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed nothing; hand the scorers the case's team so they can read the end state.

    For cases where the agent creates the notebook itself, Hedgebox is already the
    whole fixture.
    """
    return {"team_id": context.team_id}


def _event_properties(event: str, account: ChurnAccount) -> dict[str, Any]:
    # The simulation captures the signup before it links the person to an account, so a
    # real signed_up carries from_invite and no group. Planting a group on it would make
    # the event less like the ones around it, not more.
    if event == SIGNUP_EVENT:
        return {"from_invite": False}
    props: dict[str, Any] = {"$group_0": account.account_key}
    props.update(_FILE_EVENT_PROPS.get(event, {}))
    return props


def seed_churn_signal(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Plant a cohort of accounts with an unmistakable activity drop-off.

    Each planted account is a power user across the demo's early window, then goes
    completely silent — the textbook churn shape. A sound churn analysis should rank
    them near the top of its at-risk list, which is the synthetic ground truth
    ``ChurnCohortSurfaced`` grades against.
    """
    team = Team.objects.get(id=context.team_id)
    needle = build_churn_needle()
    now = timezone.now()
    # Persons exist before their first event, so the account looks real to the analysis.
    person_created_at = now - timedelta(days=needle.active_window_days[0] + 5)

    events: list[dict[str, Any]] = []
    for account in needle.accounts:
        person_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"{team.id}:{account.distinct_id}")
        person_properties = {"email": account.email, "name": account.name}
        create_person(
            team_id=team.id,
            version=0,
            uuid=str(person_uuid),
            properties=person_properties,
            is_identified=True,
            created_at=person_created_at,
        )
        create_person_distinct_id(team_id=team.id, distinct_id=account.distinct_id, person_id=str(person_uuid))
        for slot, planted in enumerate(needle.schedule):
            # Spread events within their day so ordering and per-day counts stay stable.
            timestamp = now - timedelta(days=planted.days_before_now, minutes=slot)
            properties = _event_properties(planted.event, account)
            group_columns = (
                {"group0_properties": {"name": f"{account.name} workspace"}} if "$group_0" in properties else {}
            )
            events.append(
                {
                    "event": planted.event,
                    "team": team,
                    "distinct_id": account.distinct_id,
                    "timestamp": timestamp,
                    "properties": properties,
                    "person_id": person_uuid,
                    "person_properties": person_properties,
                    **group_columns,
                }
            )
    bulk_create_events(events)

    return {
        "team_id": team.id,
        "churn_needle": {
            "token": CHURN_TOKEN,
            "silent_after_days": needle.silent_after_days,
            "accounts": [
                {
                    "index": account.index,
                    "email": account.email,
                    "name": account.name,
                    "distinct_id": account.distinct_id,
                    "account_key": account.account_key,
                }
                for account in needle.accounts
            ],
        },
    }
