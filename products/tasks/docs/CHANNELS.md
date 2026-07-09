# Channels & Threads (PostHog Code / Bluebird)

Spec for the Slack-style channel revamp. A channel is a shared feed where each
member message kicks off a task; the task renders as a card everyone in the
channel can see. Every task is owned by a channel. Each task has one thread — a
side-chain of human messages that never reach the agent unless the task author
explicitly forwards one.

## Django models

```python
class Channel(models.Model):
    class ChannelType(models.TextChoices):
        PUBLIC = "public", "Public"        # visible to the whole team
        PERSONAL = "personal", "Personal"  # the user's private "#me" channel
        PRIVATE = "private", "Private"     # visible only to its members (ChannelMembership)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=128)  # rendered as "#<name>"; personal channels are named "me"
    channel_type = models.CharField(max_length=16, choices=ChannelType, default=ChannelType.PUBLIC)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_channel"
        constraints = [
            # public channel names are unique per team (soft-deleted names are reusable)
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=Q(channel_type="public", deleted=False),
                name="task_channel_team_name_public_unique",
            ),
            # exactly one live "#me" channel per user per team
            models.UniqueConstraint(
                fields=["team", "created_by"],
                condition=Q(channel_type="personal", deleted=False),
                name="task_channel_team_user_personal_unique",
            ),
        ]


class ChannelMembership(models.Model):
    """A user's membership of a Channel — the canonical member list a channel
    carries, and the join/leave record behind it. Public channels are open feeds;
    private channels are visible only to their members. Personal channels don't
    carry membership rows (they are provisioned one-per-user)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    channel = models.ForeignKey("tasks.Channel", on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "posthog_task_channel_membership"
        constraints = [
            # a user is a member of a channel at most once
            models.UniqueConstraint(fields=["channel", "user"], name="task_channel_membership_unique"),
        ]


class Task(...):
    # every new task is owned by the channel it was kicked off in; legacy tasks stay NULL
    channel = models.ForeignKey(
        "tasks.Channel", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks", db_index=False
    )
    # + Index(fields=["channel", "-created_at"], name="posthog_task_channel_feed_idx") for the feed


class TaskThreadMessage(models.Model):
    """One human message in a task's thread. Threads are human-only side
    conversations; a message reaches the agent only when the task author
    forwards it (send_to_agent), which stamps the forwarded_* fields."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="thread_messages")
    author = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    content = models.TextField()
    forwarded_to_agent_at = models.DateTimeField(null=True, blank=True)
    forwarded_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    forwarded_run = models.ForeignKey("tasks.TaskRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_index=False)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "posthog_task_thread_message"
        indexes = [models.Index(fields=["task", "created_at"], name="task_thread_msg_task_created")]
```

### Visibility

`task_visibility_q` gains `| Q(channel__channel_type=PUBLIC)`: a task filed to a
public channel is visible to every team member (multiplayer feed). Tasks in a
personal channel remain visible only via the existing `created_by` rule.
Thread messages inherit the task's visibility.

Channel listing itself is member-gated for private channels: `GET
/task_channels/` returns every public channel plus the requester's personal
channel plus any private channels they belong to (a `ChannelMembership` row).
A private channel a user isn't in is invisible to them, including its member
list. Task-level visibility for private channels is still the existing
`created_by` rule and is tightened in a follow-up.

## API

### `/api/projects/{id}/task_channels/`

- `GET /` — list channels: all live public channels, the requester's personal
  channel, and any private channels they're a member of. Listing lazily
  `get_or_create`s the personal `#me` channel, so every user always has one.
- `POST / {name, channel_type?}` — `channel_type` defaults to `public`:
  resolve-or-create a public channel by name (`get_or_create`, so concurrent
  creates and name-bridging are race-safe). `channel_type=private` always
  creates a new members-only channel with the requester as its first member
  (private channels aren't uniquely named, so this never resolves an existing one).
- `PATCH /{id}/ {name}` — rename a public channel. Personal channels cannot be renamed.
- `DELETE /{id}/` — soft-delete a public channel. Personal channels cannot be deleted.
- `POST /{id}/join/` — add the requester to a public or private channel
  (idempotent). Joining a private channel is what makes it appear in their
  channel list. Personal channels cannot be joined.
- `POST /{id}/leave/` — remove the requester from a channel (idempotent).
  Personal channels cannot be left.
- `GET /{id}/members/` — members of the channel, oldest join first. 404 for a
  private channel the requester isn't a member of.

### Task endpoints

- `TaskWriteSerializer` accepts `channel` (UUID). Must belong to the team; a
  personal channel is only accepted from its owner.
- `TaskSerializer` / `TaskDetailDTO` emit `channel`.
- `GET /tasks/?channel=<uuid>` filters the list to a channel's feed.

### `/api/projects/{id}/tasks/{task_id}/thread_messages/`

- `GET /` — thread messages, ascending `created_at` (paginated).
- `POST / {content}` — add a message as the requester. Anyone who can see the task can post.
- `DELETE /{id}/` — author-only.
- `POST /{id}/send_to_agent/` — task author only. Signals the latest run's
  workflow with `[Thread comment from <author>] <content>` via
  `signal_task_run_user_message`, then stamps `forwarded_to_agent_at`,
  `forwarded_by`, `forwarded_run`. 400 when the task has no signalable run.

## Client (PostHog Code, bluebird mode)

- **Channel feed** — the channel view becomes a Slack-like feed: each item is
  the kickoff message (author avatar + name + prompt) with a task card
  (title, status badge, repo, replies count) underneath. The composer at the
  bottom kicks off a task owned by the channel; the author stays in the feed
  and the card updates live (poll). The existing tabs (Inbox / Artifacts /
  Recents / CONTEXT.md) stay above the feed.
- **Threads** — a collapsible right-side panel shows a task's thread: message
  list plus reply composer. Each message row has a hover menu; the task author
  gets "Send to agent" there. Forwarded messages show a "Sent to agent" badge.
  Opening a thread from a feed card shows the panel next to the feed; opening
  a task shows the same panel next to the task detail (collapsible).
- **#me** — the sidebar pins the personal channel (`#me`) above the channel
  list; it is each user's private feed.
- **Bridge** — sidebar channels remain desktop-file-system folders (CONTEXT.md,
  dashboards and artifacts stay keyed to the folder id). Each folder channel is
  mapped to a backend `Channel` by name via the resolve-or-create `POST`; the
  `#me` entry maps to the personal channel. Task ownership, feeds and threads
  key off the backend channel UUID.

## Out of scope (v1)

- Invite-based access control for private channels — v1 membership is
  self-service join/leave by channel id (the UUID is the capability); there is
  no per-channel invite/admin/role model or member-management-by-others yet.
- Tightening task-level visibility to private-channel membership (task visibility
  still keys off `created_by`; only channel listing is member-gated so far).
- Message editing and emoji reactions.
- Real-time push for feed/thread updates (clients poll; SSE can come later).
- Backfilling `channel` onto existing tasks.
