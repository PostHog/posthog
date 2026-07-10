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


def task_control_q(user_id: int | None) -> Q:
    """Filter for tasks the given user may mutate or drive (edits, runs, agent commands).

    A task is controllable if:
    - its creator matches `user_id`, or
    - it has no creator at all (legacy unowned tasks remain visible to any
      team member — they cannot be executed in any case because oauth.py
      requires `task.created_by` to mint OAuth tokens), or
    - its `origin_product` is one of `TEAM_VISIBLE_ORIGIN_PRODUCTS`, i.e. a
      team-scoped artifact (signals, onboarding) any team member may pick up.

    Deliberately narrower than ``task_visibility_q``: public-channel tasks are
    team-readable but stay creator-driven — seeing a teammate's task in a feed
    must not allow editing it, starting runs, or messaging its agent (thread
    forwarding is the explicit, author-only path for that).
    """
    return Q(created_by_id=user_id) | Q(created_by__isnull=True) | Q(origin_product__in=TEAM_VISIBLE_ORIGIN_PRODUCTS)


def task_visibility_q(user_id: int | None) -> Q:
    """Filter for tasks visible (readable) to the given user.

    Everything controllable per ``task_control_q``, plus tasks in a public
    channel: channel feeds are multiplayer, so every team member sees every
    task filed there. Personal-channel ("#me") tasks stay creator-only via
    the control rules.
    """
    return task_control_q(user_id) | Q(channel__channel_type=Channel.ChannelType.PUBLIC, channel__deleted=False)


def task_run_visibility_q(user_id: int | None) -> Q:
    """`task_visibility_q` traversed via the `task` FK on TaskRun / TaskAutomation."""
    return (
        Q(task__created_by_id=user_id)
        | Q(task__created_by__isnull=True)
        | Q(task__origin_product__in=TEAM_VISIBLE_ORIGIN_PRODUCTS)
        | Q(task__channel__channel_type=Channel.ChannelType.PUBLIC, task__channel__deleted=False)
    )
