# Channels and threads

A channel is the backend model for a space in PostHog Desktop. Tasks in a channel use that channel's access rules.
Each task has one thread. A human message reaches the agent only when the task owner forwards it.

## Models and access

| Channel type | Who can access it                   | Name rule                                          |
| ------------ | ----------------------------------- | -------------------------------------------------- |
| `public`     | Project members                     | Unique among active public channels in the project |
| `personal`   | The creator                         | One active `#me` channel per user per project      |
| `private`    | Channel members with project access | Duplicate names are allowed; use the channel ID    |

`ChannelMembership` records a private channel's members. Each row has a team, channel, user, and creation time.
The `(channel, user)` pair is unique. Public and personal channels do not use membership rows.
Any private channel member can update the member list. The creator remains a member.

The membership table has no database foreign key constraints on `team` or `user`.
This prevents the migration from locking the shared team and user tables. Django manages these relations and deletion rules.
The `channel` relation has a database foreign key constraint.

`Task.channel` can be null for older tasks and tasks from other products.
These tasks use the existing creator and product access rules.
For tasks with a channel, `Channel.visible_to_q` defines access. Task origin and ownership cannot grant additional access.
Thread messages, runs, artifacts, conversations, and task activity use the task's access rules.

`TaskThreadMessage` stores the task, author, content, and creation time.
When the task owner forwards a message, the row also records the forwarding user, time, and run.

## Channel API

Base path: `/api/projects/{id}/task_channels/`.

| Request                                         | Result                                                                                               |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `GET /`                                         | List all accessible channels, sorted by name and ID.                                                 |
| `POST / {name, channel_type, member_ids, star}` | Create a channel or return an existing public channel with the same name.                            |
| `PATCH /{id}/ {name, channel_type}`             | Rename or switch an accessible public or private channel. Personal and general spaces cannot change. |
| `DELETE /{id}/`                                 | Delete an empty public or private channel. Personal and general spaces cannot be deleted.            |
| `GET /{id}/members/`                            | List private channel members. Return an empty list for public and personal channels.                 |
| `PUT /{id}/members/ {user_ids}`                 | Replace a private channel's members. Keep the creator.                                               |

Listing channels does not create them. Call `provision_defaults` to create the default channels.
Send `limit` and `offset` to get one page with `count`, `next`, `previous`, and `results`.
Without `limit`, the response is an array of all accessible channels.

Channel creation defaults to `public`. Public names use lowercase letters and hyphens.
A private channel always gets a new UUID, even if another channel has the same name.
The requester becomes a member. The endpoint adds users from `member_ids` who have project access and skips the others.
A retry creates another private channel.

Membership replacement requires `user_ids`. Each submitted user must have project access.
An empty list removes all members except the creator.
A creator who loses project access remains in the member list but cannot access the channel.
Removing a member leaves their tasks in the channel and removes their access.
The endpoint returns 400 for invalid users or public or personal channels. It returns 404 for inaccessible channels.

A `channel_type` update switches a shared channel between `public` and `private`.
Making a channel private removes every membership row and seeds the creator and the requester.
Making a channel public removes every membership row. The name must be free among active public channels, or the request returns 400.

Channel updates, deletion, membership changes, private channel handoffs, feed posts, instructions, context generation, and stars lock the channel row.
Each write checks access after it acquires the lock. A request from a removed member fails even if it started before removal.
Membership replacement checks project access after it acquires the lock.
Handoff locks the private channel before the task. It fails if the task moved to another channel during the wait.

## Task API

- `TaskCreateSerializer` accepts a channel UUID from the same project. The requester must have access to the channel.
- An ordinary user task without a channel goes into the user's `#me` space.
- A user who controls a task can move it to a public channel, their own `#me` channel, or a private channel they belong to.
- Existing callers can still clear `channel` for compatibility.
- `TaskSerializer` and `TaskDetailDTO` return `channel`.
- `GET /tasks/?channel=<uuid>` lists tasks in a channel.

`POST /tasks/{task_id}/handoff/ {user}` transfers ownership to another project member.
Only the current owner can transfer a task. The recipient must have project access and must differ from the current owner.
All runs must have ended, and all sandbox sessions must be closed.

| Current channel        | Channel after handoff                            |
| ---------------------- | ------------------------------------------------ |
| Personal `#me` or none | The recipient's `#me` channel                    |
| Private                | The same channel; the recipient becomes a member |
| Public                 | The same channel                                 |

Future runs use the recipient for GitHub authorship and notifications.
Handoff changes the ownership version and revokes sandbox OAuth tokens for the task.
Runs from the previous ownership version become read-only. The recipient must start a new run.
Handoff clears the saved GitHub user integration and MCP credential owner.
It adds a `task_handed_off` message to the thread and notifies the recipient.

## Canvas API

Project members can create and read canvases in public channels.
Only the canvas creator can change its metadata or source.
Any project member can queue a build of the current source through `publish-current-version`.

Task sandboxes use the authenticated OAuth token user to check canvas access:

| Canvas space | Token user                    | Read | Write |
| ------------ | ----------------------------- | ---- | ----- |
| Public       | Canvas creator                | Yes  | Yes   |
| Public       | Another user or no token user | Yes  | No    |
| Personal     | Canvas creator                | Yes  | Yes   |
| Personal     | Another user or no token user | No   | No    |

A task linked to a canvas gains no additional write access.
A sandbox can create a canvas only in its task's space.

## Thread API

Base path: `/api/projects/{id}/tasks/{task_id}/thread_messages/`.

| Request                     | Result                                                                   |
| --------------------------- | ------------------------------------------------------------------------ |
| `GET /`                     | List messages by creation time, oldest first, with pagination.           |
| `POST / {content}`          | Add a message. Anyone with task access can post.                         |
| `DELETE /{id}/`             | Delete a message. Only its author can delete it.                         |
| `POST /{id}/send_to_agent/` | Forward a message to the latest run. Only the task owner can forward it. |

Forwarding uses `signal_task_run_user_message` with `[Thread comment from <author>] <content>`.
It records `forwarded_to_agent_at`, `forwarded_by`, and `forwarded_run`.
The endpoint returns 400 if no run can receive the message.

## Desktop client

The channel feed shows each task's initial message and a card with its title, status, repository, and reply count.
The message input creates a task in the channel. The feed updates through polling.
Inbox, Artifacts, Recents, and CONTEXT.md tabs appear above the feed.

A panel beside the feed or task details shows the task's thread and a reply input.
The task owner can select "Send to agent" from a message menu.
Forwarded messages show "Sent to agent". The panel can be collapsed.

The sidebar pins the user's personal `#me` channel above the channel list.
The backend channel UUID identifies the space across tasks, feeds, threads, canvases, instructions, and stars.

## Out of scope

- Per-member roles or permissions.
- Activity log entries for membership changes.
- Push notifications for membership, feed, or thread changes. Clients poll.
- Message editing and emoji reactions.
