# Slack message triggers for Loops

A `slack` trigger fires a loop when someone posts in a Slack channel PostHog is in.
The run replies in a thread on the message that started it, so the conversation stays where the work was asked for.

This is the Slack counterpart of the `github` trigger: the same match-then-fire shape, the same `filters.payload` conditions, and the same single `loop_runs.fire_loop` choke point.

## Configuration

```jsonc
{
  "type": "slack",
  "config": {
    "slack_integration_id": 42,
    "channel_ids": ["C0123ABCDEF"],
    "filters": {
      "keywords": ["incident", "sev1"],
      "payload": [{ "path": "subtype", "equals": ["file_share"] }],
    },
    "allowed_posters": { "mode": "org_members" },
  },
}
```

- `channel_ids` are Slack channel IDs, not names. Slack only sends IDs on message events, so a name would save and then never match. PostHog has to be in the channel (`/invite @PostHog`) or Slack never delivers the message.
- `keywords` is a case-insensitive substring match, and any one of them matching is enough. Omitting `keywords` runs the loop on every message in the channel.
- `payload` is the same `{path, equals}` dot-path shape the github trigger uses, for anything no named filter covers.
- All filters must match.

### What the keywords are matched against

The message text **plus its attachments and blocks**, flattened.
Alerting apps (incident tooling, monitoring relays) post their content as Block Kit blocks with an empty top-level `text`, so matching only `event["text"]` would mean a keyword trigger aimed at an alert bot never fires.

The same flattened text is what reaches the run's prompt, so an alert posted as blocks arrives as readable content rather than a raw Block Kit tree.

## Who can fire it

A matched trigger starts an unattended run holding **the loop owner's** credentials, and the message text lands in that run's prompt. `allowed_posters` is what stops an arbitrary channel member steering it.

| Mode                    | Fires on                                                                                                      |
| ----------------------- | ------------------------------------------------------------------------------------------------------------- |
| `org_members` (default) | A message from someone whose Slack identity resolves to a PostHog user with access to **this loop's project** |
| `loop_owner`            | Only the loop owner's own messages                                                                            |
| `slack_user_ids`        | Only messages whose author is on an explicit list, matched against the message's user, bot **or** app ID      |

`slack_user_ids` is the only mode that can fire on an app- or bot-posted message. The other two reject app authorship outright: an app posting on a person's behalf is indistinguishable from that person typing, so admitting it would let a relay app start a run under someone who never asked for one. It is also the mode to use for an alerting app, which posts under a bot ID with no `user` at all.

`org_members` checks **project** access (the same `UserPermissions` bar `loop_runs` holds the loop's own owner to), not organization membership. Organization membership would be wrong twice over: a Slack workspace can be connected to several organizations, and the project itself may be access-controlled, in which case an org member without access to it could otherwise fire a run there and read its report in the channel.

Two gates sit alongside the mode:

- **Externally-shared channels.** A Slack Connect channel puts the run's report in front of another company, so a loop fire waits on the same channel approval every other agent surface does.
- **Follow-up replies.** A thread bound to a loop run is _not_ an untagged-follow-up target. That path authorizes on project access alone and knows nothing about `allowed_posters`, so forwarding a reply into a live run would let a teammate steer one whose trigger says "only the owner". Loop runs are unattended by design.

## Firing and reporting back

`fire_key` is Slack's `event_id`, falling back to `channel:ts` when the delivery carries none — an empty fire key would be identical for every message on a trigger, so dedup would swallow all but the first.

The fire carries a per-fire `slack_thread_target`, which does two things:

- sets `pending_dispatch.slack_thread_context` on the run, which carries lifecycle updates (progress, completion, errors) into the thread;
- writes a `SlackThreadTaskMapping` row, which is what the end-of-turn relay resolves to deliver the agent's report.

The binding is **per fire, not per loop**: a channel trigger opens a new thread under each message it matches. A top-level post threads under itself; a reply keeps its existing thread.

When two loops match the same message, the first one to fire wins the thread binding (`get_or_create`) — the second still posts its lifecycle updates there via its own `slack_thread_context`, but its final report does not land in the thread.

## Guardrails

- **Self-trigger.** A reply inside a thread that already belongs to an agent run never fires a trigger. Without it a loop's own report, posted into the thread it was triggered from, matches the same keyword and re-triggers the loop indefinitely.
- **Cross-team.** Matching is scoped to the integration's actual owning team, not the caller-supplied `slack_integration_id`, so a trigger can't be pointed at another project's workspace.
- **Throttle.** A fixed window per `(workspace, channel)` ahead of the per-loop and per-team rate caps, sized above a busy channel's real volume. Fails open.
- **Lazy poster resolution.** Resolving a Slack user costs a `users.info` round trip, so it happens only after a trigger has already matched on channel and content — never on every message in the channel.

## The hot path

`message` events are Slack's firehose, and the handler used to drop every top-level channel post before any DB hit. Admitting them is guarded by `slack_workspace_has_loop_triggers`, a cached workspace-level lookup: a workspace with no Slack triggers pays one cached read per message and nothing else. A newly saved trigger can take up to the cache TTL to start firing.

A region holding no install for a workspace answers `True` rather than `False`. It cannot see the other region's triggers, and a `False` there would drop the message before the region gate that would have forwarded it — so a workspace installed in the other region would silently only ever fire on thread replies. The trade-off is that such workspaces now forward their channel messages cross-region, where the receiving region applies the real (cached) check.

## Rollout

Behind the `slack-app-loop-triggers` flag, evaluated per organization. A workspace connected to several organizations gates each install on its own org, so one org's verdict never decides for the rest. With the flag off a saved `slack` trigger simply never fires and channel messages take exactly the path they took before the feature existed.

## Where the code lives

| Concern             | File                                                                               |
| ------------------- | ---------------------------------------------------------------------------------- |
| Matching and firing | `products/tasks/backend/loop_slack_events.py`                                      |
| Event dispatch      | `products/slack_app/backend/api.py` (`_dispatch_slack_loop_triggers`)              |
| Thread binding      | `products/tasks/backend/logic/services/loop_runs.py` (`_bind_slack_thread`)        |
| Config validation   | `products/tasks/backend/presentation/serializers_loops.py`                         |
| Trigger editor      | `products/desktop/packages/ui/src/features/loops/components/LoopTriggerEditor.tsx` |
