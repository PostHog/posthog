"""Deterministic churn-needle definition for the notebook analysis evals.

Pure and Django-free, so it stays unit-testable outside the app: it only names the
accounts to plant and the shape of their activity. The seeder turns this into
ClickHouse persons and events, and the scorer checks the notebook surfaces them.

Every identifier carries ``CHURN_TOKEN``, so an analysis that lists at-risk accounts
by email, by name, by distinct id, or by account key all surface the same searchable
marker — which is what lets the scorer grade the prediction without knowing how the
agent chose to group.
"""

from __future__ import annotations

from posthog.dataclasses import frozen

CHURN_TOKEN = "hollowbrook"

# First names keep the planted accounts distinguishable from one another; the shared
# CHURN_TOKEN in the surname, domain, and account key is what the scorer matches on.
_FIRST_NAMES = ("ada", "bianca", "caleb", "dara", "elias", "farah", "gideon", "hana")

# One "active session" the planted power users repeat until they go silent. The mix spans
# the signals the cases ask about — logins, uploads, downloads, and sharing — so the same
# cohort reads as churn whichever behaviour an analysis keys on.
_SESSION_EVENTS = ("logged_in", "uploaded_file", "uploaded_file", "downloaded_file", "shared_file_link")

SIGNUP_EVENT = "signed_up"


@frozen
class ChurnAccount:
    index: int
    distinct_id: str
    account_key: str
    email: str
    name: str


@frozen
class PlantedEvent:
    event: str
    days_before_now: int


@frozen
class ChurnNeedle:
    accounts: tuple[ChurnAccount, ...]
    schedule: tuple[PlantedEvent, ...]
    silent_after_days: int
    active_window_days: tuple[int, int]


def build_churn_needle(
    count: int = 6,
    *,
    oldest_active_day: int = 120,
    newest_active_day: int = 70,
    session_stride_days: int = 4,
) -> ChurnNeedle:
    """Build the planted cohort: ``count`` accounts, each signing up
    ``oldest_active_day`` days ago, very active until ``newest_active_day``, then silent.

    The gap between ``newest_active_day`` and today is the churn signal — power users
    who stopped — so keep it wide relative to the demo's ~120-day window.
    """
    if not 1 <= count <= len(_FIRST_NAMES):
        raise ValueError(f"count must be between 1 and {len(_FIRST_NAMES)}")
    if oldest_active_day <= newest_active_day:
        raise ValueError("oldest_active_day must be greater than newest_active_day")

    accounts = tuple(
        ChurnAccount(
            index=i,
            distinct_id=f"{CHURN_TOKEN}-user-{i}",
            account_key=f"{CHURN_TOKEN}-{i}",
            email=f"{name}.{CHURN_TOKEN}@example.com",
            name=f"{name.capitalize()} {CHURN_TOKEN.capitalize()}",
        )
        for i, name in enumerate(_FIRST_NAMES[:count])
    )
    # The signup comes first: every simulated account emits ``signed_up`` before anything
    # else, and the simulation makes it a precondition for logging in, uploading, and
    # sharing. A cohort without one is a shape the fixture never holds, so an analysis
    # that builds its customer base from signups would drop every planted account.
    schedule = (
        PlantedEvent(event=SIGNUP_EVENT, days_before_now=oldest_active_day),
        *(
            PlantedEvent(event=event, days_before_now=day)
            for day in range(oldest_active_day - 1, newest_active_day - 1, -session_stride_days)
            for event in _SESSION_EVENTS
        ),
    )
    return ChurnNeedle(
        accounts=accounts,
        schedule=schedule,
        silent_after_days=newest_active_day,
        active_window_days=(oldest_active_day, newest_active_day),
    )
