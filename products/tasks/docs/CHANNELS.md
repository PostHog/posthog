# Channels & Threads (PostHog Desktop / Bluebird)

A channel is the backend model for a space. Public spaces are visible to project members.
`#me` is a private space that only its owner can access. A task with a channel inherits
that channel's visibility. Null-channel tasks keep the legacy creator and product-origin
rules until their product adopts spaces.

Each task has one thread. Human messages reach the agent only when the task author
explicitly forwards one.

## Django models

```python
class Channel(models.Model):
    class ChannelType(models.TextChoices):
        PUBLIC = "public", "Public"        # visible to the whole team
        PERSONAL = "personal", "Personal"  # the user's private "#me" channel

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


class Task(...):
    # Ordinary user tasks get a channel; legacy and product tasks can remain NULL.
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

A task with a channel uses only channel visibility:

- `PUBLIC` is readable by project members.
- `PERSONAL` is readable only by `Channel.created_by` and is shown as a private space.
- Task origin and creator fallbacks never widen a task with a channel.

A null-channel task uses the legacy creator and team-readable origin rules. Thread
messages, runs, artifacts, conversations, and task activity inherit task visibility.
A future selected-member private space can extend `Channel.visible_to_q` with channel
membership without adding permissions to Task.

## API

### `/api/projects/{id}/task_channels/`

- `GET /` — list channels: all live public channels plus the requester's
  personal channel. Listing lazily `get_or_create`s the personal `#me` channel,
  so every user always has one.
- `POST / {name}` — resolve-or-create a public channel by name
  (`get_or_create`, so concurrent creates and name-bridging are race-safe).
- `PATCH /{id}/ {name}` - any project member can rename or configure a public channel. Private `#me` spaces cannot be renamed.
- `DELETE /{id}/` - any project member can delete an empty public channel. Private `#me` and non-empty spaces cannot be deleted.

### Task endpoints

- `TaskCreateSerializer` accepts `channel` (UUID). It must belong to the team. A
  private `#me` space is accepted only from its owner.
- Omitting `channel` for an ordinary user task files it into the user's `#me` space.
- A task controller can move a task by updating `channel` to a public or owned private space. Existing callers can still clear `channel` for legacy compatibility.
- `TaskSerializer` / `TaskDetailDTO` emit `channel`.
- `GET /tasks/?channel=<uuid>` filters the list to a channel's feed.
- `POST /tasks/{task_id}/handoff/ {user}`: hand a task off to a colleague. The
  requester must own the task; the target must have access to the project and not
  be the current owner. Ownership (`created_by`)
  moves to the recipient, so they drive the task afterwards and future runs
  resolve GitHub authorship and notification recipients from them. A task in a
  private `#me` space (or with no channel) moves into the recipient's `#me`, so a
  handoff never strands a task the recipient can't open; a task in a shared space
  stays there. All task runs must be terminal and every sandbox session must be
  closed before a handoff. The handoff rotates the task's server-owned ownership
  version, revokes task-bound sandbox OAuth tokens, and makes runs from the old
  ownership version read-only. The recipient must start a fresh run. The handoff
  also clears the stored GitHub user-integration preference and any borrowed MCP
  credential owner, posts a system `task_handed_off` announcement into the task's
  thread, and notifies the recipient.

### Canvas endpoints

- Project members can create and read Canvases in public channels.
- Only a Canvas creator can change Canvas metadata or source.
- Any project member can queue a build for the current source version through `publish-current-version`.

Task sandboxes use the authenticated OAuth token user for the creator boundary across public and personal spaces:

| Canvas space | Token user                    | Read | Write |
| ------------ | ----------------------------- | ---- | ----- |
| Public       | Canvas creator                | Yes  | Yes   |
| Public       | Another user or no token user | Yes  | No    |
| Personal     | Canvas creator                | Yes  | Yes   |
| Personal     | Another user or no token user | No   | No    |

An exact task-to-Canvas link does not grant additional write access. Canvas creation remains limited to the bound task's space.

### `/api/projects/{id}/tasks/{task_id}/thread_messages/`

- `GET /` — thread messages, ascending `created_at` (paginated).
- `POST / {content}` — add a message as the requester. Anyone who can see the task can post.
- `DELETE /{id}/` — author-only.
- `POST /{id}/send_to_agent/` — task author only. Signals the latest run's
  workflow with `[Thread comment from <author>] <content>` via
  `signal_task_run_user_message`, then stamps `forwarded_to_agent_at`,
  `forwarded_by`, `forwarded_run`. 400 when the task has no signalable run.

## Client (PostHog Desktop, bluebird mode)

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
- **One identity** — the backend `Channel` UUID keys everything: task
  ownership, feeds, threads, canvases (`Canvas.channel`), CONTEXT.md
  instructions, and per-user stars. (The former desktop-file-system folder
  bridge — folders mapped to channels by name — was retired when canvases
  became first-class rows; see `products/canvas/`.)

## Out of scope (v1)

- Selected-member private spaces and channel membership.
- Message editing and emoji reactions.
- Real-time push for feed/thread updates (clients poll; SSE can come later).
