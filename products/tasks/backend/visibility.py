"""Task visibility filters.

Kept out of the API module so import-light consumers (the file-system registration in
posthog.api.file_system.registrations, which loads at django.setup()) don't pull the whole
tasks API surface — its module-scope imports reach jsonschema and the modal SDK.
"""

from django.db.models import Q

from products.tasks.backend.models import Channel, Task

# Origin products whose tasks are team-scoped rather than personal: every team member
# can view them regardless of who created them.
# - SIGNAL_REPORT / SIGNALS_SCOUT: pipeline artifacts attached to a system-picked
#   `created_by` so the agent can mint an OAuth token, but they are not personal.
# - ONBOARDING: the "Set up PostHog" wizard task. Its `created_by` is the real person who
#   went through onboarding (not a system pick), but we surface it team-wide so anyone on
#   the team can see and pick up the setup, not just whoever happened to start it.
# - HOGDESK: support-desk Code threads. The task is pinned to the support ticket via a
#   shared ticket tag, so any agent opening the ticket resumes the same thread — it must
#   be viewable by the whole team, not just the agent who started it.
TEAM_VISIBLE_ORIGIN_PRODUCTS = [
    Task.OriginProduct.SIGNAL_REPORT,
    Task.OriginProduct.SIGNALS_SCOUT,
    Task.OriginProduct.ONBOARDING,
    Task.OriginProduct.HOGDESK,
]


def task_visibility_q(user_id: int | None) -> Q:
    """Filter for tasks visible to the given user.

    A task is visible if:
    - its creator matches `user_id`, or
    - it has no creator at all (legacy unowned tasks remain visible to any
      team member — they cannot be executed in any case because oauth.py
      requires `task.created_by` to mint OAuth tokens), or
    - its `origin_product` is one of `TEAM_VISIBLE_ORIGIN_PRODUCTS`, i.e. a
      team-scoped artifact (signals, onboarding) that any team member should see, or
    - it lives in a public channel: channel feeds are multiplayer, so every team
      member sees every task filed there. Personal-channel ("#me") tasks stay
      creator-only via the first rule.
    """
    return (
        Q(created_by_id=user_id)
        | Q(created_by__isnull=True)
        | Q(origin_product__in=TEAM_VISIBLE_ORIGIN_PRODUCTS)
        | Q(channel__channel_type=Channel.ChannelType.PUBLIC, channel__deleted=False)
    )


def task_run_visibility_q(user_id: int | None) -> Q:
    """`task_visibility_q` traversed via the `task` FK on TaskRun / TaskAutomation."""
    return (
        Q(task__created_by_id=user_id)
        | Q(task__created_by__isnull=True)
        | Q(task__origin_product__in=TEAM_VISIBLE_ORIGIN_PRODUCTS)
        | Q(task__channel__channel_type=Channel.ChannelType.PUBLIC, task__channel__deleted=False)
    )
