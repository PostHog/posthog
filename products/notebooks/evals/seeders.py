"""Seeder hooks for the notebook eval cases.

The seeder contract takes no per-case parameters, so each seeded state gets its own
function. Every one of them returns ``team_id``: it is the only channel a scorer has
for reaching the case's own team, and the notebook scorers grade the documents and run
rows the agent left there rather than what the transcript claims.

Seeders run synchronously in the case's freshly cloned team, so they can write straight
to ClickHouse with the same ``TEST=1`` helpers the pytest suites use, and mirror what they
plant into the persons database the way cloning the team mirrors the demo's own persons.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from posthog.models import Team
from posthog.models.event.util import bulk_create_events
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.util import raw_create_group_ch
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_distinct_id, insert_seed_person

from products.notebooks.evals.synthesizer import CHURN_TOKEN, SIGNUP_EVENT, ChurnAccount, build_churn_needle
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

# Realistic props for the planted file events, so a churn query that groups or filters on
# file properties still sees well-formed rows. Fixed values keep the seed deterministic.
_FILE_EVENT_PROPS: dict[str, dict[str, Any]] = {
    "uploaded_file": {"file_type": "application/pdf", "file_size_b": 5_242_880, "used_mb": 5_242_880},
    "downloaded_file": {"file_type": "application/pdf", "file_size_b": 5_242_880, "file_name": "quarterly-report"},
    "shared_file_link": {"file_type": "application/pdf", "file_size_b": 5_242_880},
}

# Hedgebox registers its "account" group type at index 0, which is what ``$group_0`` on the
# planted events points at.
_ACCOUNT_GROUP_TYPE_INDEX: GroupTypeIndex = 0
_MB_PER_PLANTED_FILE = 5


def _workspace_name(account: ChurnAccount) -> str:
    return f"{account.name} workspace"


def _person_uuid(team_id: int, account: ChurnAccount) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{team_id}:{account.distinct_id}")


def _person_properties(account: ChurnAccount) -> dict[str, Any]:
    return {"email": account.email, "name": account.name}


def _seed_persons_db(
    team_id: int,
    accounts: tuple[ChurnAccount, ...],
    *,
    created_at: datetime,
    last_seen_at: datetime,
) -> None:
    """Mirror the planted persons into the persons database.

    Cloning a team syncs the demo's own persons there, and personhog serves exact person
    lookups from it, so a person planted only in ClickHouse would be the one account in
    the team that a lookup by id or distinct id cannot hydrate.
    """
    with persons_db_connection(writer=True, autocommit=True) as conn:
        for account in accounts:
            person_id = insert_seed_person(
                conn,
                team_id=team_id,
                properties=_person_properties(account),
                is_identified=True,
                uuid=_person_uuid(team_id, account),
                version=0,
                created_at=created_at,
                last_seen_at=last_seen_at,
            )
            insert_seed_distinct_id(conn, team_id=team_id, person_id=person_id, distinct_id=account.distinct_id)


def _group_properties(account: ChurnAccount, uploads: int) -> dict[str, Any]:
    """The account group as the demo writes it: name, industry, storage, plan, team size."""
    return {
        "name": _workspace_name(account),
        "industry": None,
        "used_mb": uploads * _MB_PER_PLANTED_FILE,
        "file_count": uploads,
        "plan": "personal/free",
        "team_size": 1,
    }


# Hedgebox also exposes its uploads as a warehouse table, derived once from the master
# simulation into a CSV every case team shares. The planted cohort only reaches ClickHouse
# ``events``, so that table would show an upload history without the churners in it: an
# agent that queried it would build a sound analysis and still miss the needle. Hide it so
# every source the agent can reach agrees on who uploaded what.
_STALE_WAREHOUSE_TABLES = ("uploaded_files",)


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


def _hide_stale_warehouse_tables(team_id: int) -> None:
    for table in DataWarehouseTable.objects.filter(team_id=team_id, name__in=_STALE_WAREHOUSE_TABLES):
        table.soft_delete()


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
    # Spread events within their day so ordering and per-day counts stay stable. Every
    # account repeats the same schedule, so the timestamps are worked out once.
    planted_at = [
        now - timedelta(days=planted.days_before_now, minutes=slot) for slot, planted in enumerate(needle.schedule)
    ]
    newest_planted_at = max(planted_at)
    # The signup opens the account, so the group starts there.
    account_created_at = min(planted_at)
    # Persons exist before their first event, so the account looks real to the analysis.
    person_created_at = now - timedelta(days=needle.active_window_days[0] + 5)
    uploads = sum(1 for planted in needle.schedule if planted.event == "uploaded_file")

    _seed_persons_db(team.id, needle.accounts, created_at=person_created_at, last_seen_at=newest_planted_at)

    events: list[dict[str, Any]] = []
    for account in needle.accounts:
        person_uuid = _person_uuid(team.id, account)
        person_properties = _person_properties(account)
        create_person(
            team_id=team.id,
            version=0,
            uuid=str(person_uuid),
            properties=person_properties,
            is_identified=True,
            created_at=person_created_at,
            # HogQL reads persons.last_seen_at as the person's most recent event, and the
            # writer defaults it to the time of the write. Left alone, the planted cohort
            # would read as the most recently active people in the team — the opposite of
            # the churn shape these events describe.
            last_seen_at=newest_planted_at,
        )
        create_person_distinct_id(team_id=team.id, distinct_id=account.distinct_id, person_id=str(person_uuid))
        # HogQL reads account.key and account.properties through the groups table, so an
        # analysis that starts from the account list only sees accounts with a group row.
        # ClickHouse only, like the demo generator, so a planted account reads the same as
        # a simulated one.
        raw_create_group_ch(
            team_id=team.id,
            group_type_index=_ACCOUNT_GROUP_TYPE_INDEX,
            group_key=account.account_key,
            properties=_group_properties(account, uploads),
            created_at=account_created_at,
        )
        for planted, timestamp in zip(needle.schedule, planted_at):
            properties = _event_properties(planted.event, account)
            group_columns = (
                {"group0_properties": {"name": _workspace_name(account)}} if "$group_0" in properties else {}
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
    _hide_stale_warehouse_tables(team.id)

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
