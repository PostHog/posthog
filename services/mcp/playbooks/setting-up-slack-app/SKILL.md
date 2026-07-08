# Skill — setting up a Slack app for an agent

End-to-end script for getting a Slack-triggered agent live: create a
Slack app at the Slack side, punch out the two required secrets
(signing secret + bot token) so the agent can be promoted, **then**
hand the user the Request URLs to wire into Slack. Load this whenever
a user wants their agent to listen on Slack OR you're authoring a
fresh agent whose spec includes a `slack` trigger.

## The critical ordering

**Slack's Event Subscriptions Request URL only validates against a
LIVE agent revision.** When the user pastes the URL into Slack,
Slack immediately POSTs a `url_verification` challenge to it; the
agent-ingress handler resolves the slug → live revision → checks the
signing secret → echoes the challenge back. Every one of those steps
fails if the agent doesn't have a live revision yet.

So the order is non-negotiable:

```text
1. Slack-side prep ............ create app, copy creds
2. PostHog-side wiring ........ punch out secrets, validate, freeze, PROMOTE
3. Slack-side activation ...... NOW paste the Request URL, subscribe to events
```

If you reverse steps 2 and 3, the user pastes the URL into Slack and
sees "Your URL didn't respond" because there's no live revision to
verify against. They retry, get confused, blame the tunnel — wasted
time. **Always promote first, then surface the URL.**

## Fast path — create the app from a manifest (prefer this)

Don't make the user hand-pick OAuth scopes and bot event subscriptions —
they get it wrong (classically: `auto_resume_threads` on but
`message.channels` never subscribed, so thread replies never arrive).
Instead, call **`posthog__agent-applications-revisions-slack-manifest`**
(MCP tool) for the
revision. It returns `{ manifest, notes, events_url, interactivity_url }`
where `manifest` is a ready-to-paste Slack app manifest whose scopes +
bot events are **derived from this agent's slack trigger config and
tools** — so they're correct by construction.

Hand the user:

1. The deep link: <https://api.slack.com/apps?new_app=1> → "From an app
   manifest" → pick the workspace → paste the `manifest` JSON (JSON tab).
2. Each line in `notes` (e.g. "invite the bot to its channels").

This replaces the manual scope/event picking in Step 1.3 + Step 3.2
below — keep those as the by-hand fallback for when the user would
rather click through, or to explain what a field does.

**The ordering still holds**, because creating from a manifest that
carries the events Request URL makes Slack verify it immediately:

- The manifest still needs `SLACK_SIGNING_SECRET` + `SLACK_BOT_TOKEN`
  set + the agent promoted before that URL will verify. So: create the
  app from the manifest, grab the signing secret + bot token from it,
  punch them out + promote (Step 2), then back in Slack hit "Retry" on
  the events Request URL — now live, it verifies.
- If `events_url` came back null (no public ingress URL), say so and
  stop — same as the manual flow; the manifest's URL is a placeholder.

PostHog Code surfaces the same manifest under the agent's **Connections**
tab ("Set up Slack" card) — point PostHog Code users there instead of pasting
JSON into chat.

## Prereqs you can detect

Before walking the user through anything, gather:

1. **Agent slug.** From `get_context` or whichever agent the user is
   configuring. Required for the events URL.
2. **`slack_events_url` / `slack_interactivity_url` on the agent.**
   `posthog__agent-applications-retrieve` returns both. They're `null` when the
   PostHog deployment hasn't set `AGENT_INGRESS_PUBLIC_URL`. Hold onto
   the values — you'll surface them at step 3 below, AFTER promote.
3. **Current env state.** `posthog__agent-applications-env-keys-get` for
   `SLACK_SIGNING_SECRET` and `SLACK_BOT_TOKEN` — tells you whether
   you're setting fresh or rotating.

If `slack_events_url` is `null`, **stop and tell the user before doing
anything else**:

> Heads up: this deployment doesn't have a public agent-ingress URL
> configured (`AGENT_INGRESS_PUBLIC_URL` is unset), so I can't give
> you the URL to paste into Slack. In local dev: run
> `bin/agent-tunnel`, copy the printed URL, export
> `AGENT_INGRESS_PUBLIC_URL=<url>`, restart the posthog web process,
> then come back here. In prod: this is a deployment-config gap —
> the platform team needs to set the env var on Django.

You can stop there. Don't pretend to walk the rest of the flow without
a URL — even if you got the agent live, the user couldn't activate it.

## Step 1 — Slack-side prep (no URL handoff yet)

Tell the user, in order. Keep each step terse — the user is
context-switching between this chat and the Slack admin UI, so don't
bury the action.

1. **Create the app.**
   Open <https://api.slack.com/apps>, click "Create New App", "From
   scratch". Pick any name + workspace. Land on the app's
   Basic Information page.

2. **Copy the signing secret.**
   Settings → Basic Information → "App Credentials" → copy the
   Signing Secret. Hold it for the punch-out in step 2.

3. **Add OAuth scopes.**
   Features → OAuth & Permissions → "Scopes" → "Bot Token Scopes".
   Add at minimum:
   - `chat:write` — post messages
   - `channels:history` + `groups:history` — read channels the bot
     is in (for `@posthog/slack-read-channel` /
     `@posthog/slack-read-thread`)
   - `reactions:write` — required when the agent uses
     `@posthog/slack-react` OR when the slack trigger has
     `ack_reaction` set (the ingress posts the configured emoji as
     an immediate ack on every accepted event). Without this scope
     the Slack API returns `missing_scope` and the ack is silently
     dropped — the session still enqueues, but the user sees no
     "I saw it" feedback in Slack.
   - `app_mentions:read` — required if the agent will subscribe to
     `app_mention` events (added later in step 3 of this skill)
     Match scopes to the tools the agent actually uses; over-scoping
     is a workspace-admin red flag.

   **Inspect the spec before listing scopes.** Read `spec.tools[]` AND
   `spec.triggers[].config.ack_reaction` and only ask for scopes the
   agent will actually exercise. If you're configuring an existing
   agent and the user reports `ack_reaction_failed` /
   `missing_scope` in the ingress logs (see "Common failure modes"),
   add `reactions:write` to the bot scopes and re-install the app —
   Slack invalidates the scope set on each install, so adding scopes
   after the fact requires a re-install banner to be clicked. The
   same `xoxb-...` token then carries the new scope; no PostHog-side
   re-punch-out needed.

4. **Install to workspace.**
   Same page → "Install to <workspace>" at the top. Authorize.
   Slack redirects back to the app dashboard and reveals the
   **Bot User OAuth Token** (starts with `xoxb-`). Copy it.

5. **Note the workspace's team id.** The agent's
   `spec.triggers[].config.trusted_workspaces` must contain this id
   or events will 403. Slack hides it; the easiest path is the
   Slack-side URL after install
   (`https://app.slack.com/client/<team_id>/...`), or `T...` IDs the
   user often already knows. If the agent should accept any
   workspace (public bot), set it to the literal string `"*"`.

**Do NOT touch Event Subscriptions or Interactivity yet.** Those tabs
require a live URL that responds to verification — that comes at
step 3 of this skill, after promote.

## Step 2 — PostHog-side wiring (get the agent live)

Now you take over. Loop, in order:

1. **Punch out `SLACK_SIGNING_SECRET`** with the value from prep step 2.

   ```text
   set_secret { agent_slug, secret: "SLACK_SIGNING_SECRET",
                purpose: "Verifies inbound Slack event signatures." }
   ```

2. **Punch out `SLACK_BOT_TOKEN`** with the value from prep step 4.

   ```text
   set_secret { agent_slug, secret: "SLACK_BOT_TOKEN",
                purpose: "Lets the agent call Slack APIs as the bot user." }
   ```

3. **Verify `spec.triggers[].config.trusted_workspaces` includes the
   workspace id from prep step 5** (or is `"*"`). If not, open the draft
   revision and patch the spec before freeze.

4. **Decide conversation style — see "Tuning the slack trigger" below
   before freeze.** The three optional fields (`mention_only`,
   `auto_resume_threads`, `ack_reaction`) control how the bot reacts
   to inbound messages. Defaults are back-compat ("react to anything
   in the channel"); most authors will want to opt into the
   `mention_only + auto_resume_threads` pair, which is what users
   usually mean by "behave like a normal Slack bot".

5. **Validate, freeze, promote.** The validate step will refuse if
   either secret is missing; promote re-checks at the gate. Both
   give clear error strings — surface them verbatim if hit. **Get
   explicit consent before promote per hard rule #3** — but make the
   ask in the same message that lists what's about to ship so the
   user can say "yes" without re-reading the thread.

After promote returns `state=live`, the agent is reachable from the
outside world — Slack's URL verification will now succeed. Move on
to step 3.

## Step 3 — Slack-side activation (now safe to paste the URL)

Hand the URLs back to the user. Format them as direct copy-paste:

> Promoted. Two URLs to paste into your Slack app now:
>
> - **Event Subscriptions → Request URL**:
>   `<slack_events_url>`
> - **Interactivity & Shortcuts → Request URL** (optional, only if
>   the agent sends message buttons or elevation prompts):
>   `<slack_interactivity_url>`
>
> Tell me when the green check appears on the events URL, then
> we'll subscribe to bot events and smoke-test.

Tell the user, in order:

1. **Set the Event Subscriptions URL.**
   Slack app dashboard → Features → Event Subscriptions → toggle
   "Enable Events" on. Paste the events URL into "Request URL".
   Slack pings the `url_verification` endpoint; with the agent live
   and the signing secret saved, it ticks green within ~2 seconds.

2. **Subscribe to bot events.**
   Same page → "Subscribe to bot events". Add what the agent needs.
   The choice maps to the conversation-style decision in step 2.4
   above:
   - `app_mention` — fires when someone @-mentions the bot. Always
     subscribe to this if the user wants the bot to respond to
     @-mentions at all.
   - `message.channels` — every message in channels the bot's in.
     Subscribe in addition to `app_mention` when the user picked
     `auto_resume_threads` (the trigger needs the thread-reply
     events to flow in) OR when the bot should react to everything
     (no `mention_only` gate). Skip this when the bot is purely
     mention-driven and never auto-resumes — saves Slack
     bandwidth.
     Save.

3. **(Optional) Set the Interactivity URL.**
   Features → Interactivity & Shortcuts → toggle on. Paste the
   interactivity URL into "Request URL". Save. Skip if the agent
   never sends interactive blocks.

4. **Invite the bot to a channel.** Slack-side, `/invite @<your-bot>`
   in any channel you want it to listen in. The bot has to be a
   member or `message.channels` events never fire.

## Step 4 — Smoke test

Tell the user: "Mention the bot in the channel you invited it to
(`@<bot> hi`). I'll watch `sessions-list` for the new session and
we can debug from there if nothing arrives."

Then poll `posthog__agent-applications-sessions-list` filtered to the slack
trigger and the last few minutes. If nothing shows up within ~10s,
check the agent-ingress logs for a 401 (signing secret mismatch),
403 (`workspace_not_trusted`), or 404 (`no_slack_trigger` — spec
didn't actually freeze with the slack trigger).

## Tuning the slack trigger

The slack trigger config has five optional fields beyond
`channel_id` / `trusted_workspaces`. Defaults are back-compat ("react
to anything the bot can see", owner-only threads, no DMs); for most new
agents the user actually wants the opt-in flags.

| Field                          | Type             | Default | What it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------ | ---------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mention_only`                 | `boolean`        | `false` | When `true`, only `app_mention` events seed sessions. Plain `message` events (delivered because the bot subscribed to `message.channels`) are dropped at the trigger. Use when the agent should only react when someone explicitly @-mentions it.                                                                                                                                                                                                                                                                                        |
| `auto_resume_threads`          | `boolean`        | `false` | Relaxes `mention_only` for replies in threads the bot already owns. When a `message` event comes in with a `thread_ts` matching an existing session's `external_key`, the trigger accepts it. The seeded message carries `mention: false` so the model can judge whether it was addressed. No effect when `mention_only` is `false`.                                                                                                                                                                                                     |
| `allow_workspace_participants` | `boolean`        | `false` | Who may advance an open thread. Every Slack session is owned by the user who opened it. Default (`false`): only that user can drive the thread — a reply from anyone else is parked as an elevation request and the bot posts an in-thread "only the starter can continue this" reply. `true`: any user in a `trusted_workspaces` workspace can post into the thread and advance the session (shared/team threads). The real sender is always recorded for audit either way.                                                             |
| `ack_reaction`                 | `string` (emoji) | unset   | Emoji name (no colons, e.g. `"eyes"` or `"thinking_face"`) the ingress posts as `reactions.add` against the inbound message immediately on accept — before the runner produces a turn. Fire-and-forget; failures (revoked token, slack 5xx, `already_reacted`) are silently swallowed.                                                                                                                                                                                                                                                   |
| `allow_direct_messages`        | `boolean`        | `false` | When `true`, the bot also handles direct messages (`channel_type: "im"`) and group DMs (`"mpim"`) — "talk to it as an app", not just channel mentions. A DM is inherently directed at the bot, so it bypasses `mention_only`; each DM conversation is one rolling session keyed per-channel (`slack:<channel>`), idle-reset by the platform sweep. The generated manifest subscribes `message.im`/`message.mpim`, adds `im:history`/`mpim:history`, and enables the App Home Messages tab. **New scopes ⇒ the app must be reinstalled.** |

### How to pick

Walk the user through the choice as a question, not a config dump:

> Three behavioural knobs on the slack trigger. The defaults
> ("react to everything the bot can see") match a Slackbot-style bot;
> most authors want one of:
>
> - **"Only when I @-mention you"** — set `mention_only: true`. Pair
>   with `app_mention` in Slack-side event subscriptions; drop
>   `message.channels`. Best for utility bots in busy channels.
> - **"@-mention to start, then just talk in the thread"** — set
>   both `mention_only: true` AND `auto_resume_threads: true`. Pair
>   with both `app_mention` AND `message.channels`. Best for
>   conversational bots — the user @-mentions once, then the bot
>   stays in the thread until it dies.
> - **"React to everything"** — leave both unset (defaults).
>   Subscribe to `message.channels`. Best for digest / monitoring
>   bots that should see all channel chatter.
>
> And optionally, `ack_reaction: "eyes"` for an instant emoji
> reaction so the user sees you saw the message before you produce
> a real response — useful when the first turn is slow.

Then a separate, orthogonal question — **who** may drive a thread:

> By default a thread belongs to whoever started it: only they can
> continue it, and if a colleague replies I'll tell them (in-thread)
> that only the starter can drive it. Want to open threads up so
> anyone in the workspace can chime in and I'll respond to all of
> them? That's `allow_workspace_participants: true`. Best for shared
> "ask the bot" threads; leave it off for 1:1 assistant threads.

And — orthogonal again — **can people DM the bot directly**:

> Want to be able to open a direct message with the bot and just talk
> to it 1:1, instead of always @-mentioning it in a channel? That's
> `allow_direct_messages: true`. Each DM is its own rolling
> conversation. Heads-up: this adds the `im:history` scope, so once I
> regenerate the manifest you'll need to **reinstall the app** for the
> new scope to take, and the bot's Messages tab has to be enabled
> (the manifest does that automatically). Great for personal-assistant
> bots; leave it off for bots that should only live in channels.

### Wiring it

The fields land on `spec.triggers[].config` for the slack trigger.
Open the draft revision and patch the spec before freeze (or do it
inline at trigger-creation time):

```json
{
  "type": "slack",
  "config": {
    "trusted_workspaces": ["T01ABC"],
    "mention_only": true,
    "auto_resume_threads": true,
    "allow_workspace_participants": false,
    "ack_reaction": "eyes",
    "allow_direct_messages": false
  }
}
```

If the user picks `mention_only: true` without `auto_resume_threads`,
warn them once that the bot won't see thread replies unless they
@-mention every time — most people want both together. If they pick
`auto_resume_threads` without `mention_only`, tell them it's a no-op
(the gate it relaxes never fires).

`allow_workspace_participants` is independent of the mention/thread
knobs — it only changes who may advance an already-open thread, never
which events arrive. Owner-only (default) is the fail-closed choice;
flip it on only when the user explicitly wants a shared thread.

`allow_direct_messages` is also independent — it only adds the DM
surface, it doesn't change channel behaviour. When you flip it on,
**regenerate the manifest** (`posthog__agent-applications-revisions-slack-manifest`)
and tell the user to reinstall the app: it adds `im:history` /
`mpim:history` (new scopes only minted at install) and enables the App
Home Messages tab, without which Slack won't let anyone open a DM.

## Letting the bot read the thread it's in

A common ask: "if someone replies 'what does this alert mean?', the
bot should be able to see the original alert message in the thread."
That's not automatic — the seed the model receives carries the
current message text plus the `[slack]` envelope (channel / ts /
thread_ts), **not** the rest of the thread. To give the agent the
surrounding context, add the read tool to its `spec.tools[]`:

- **`@posthog/slack-read-thread`** — fetches the parent message + all
  replies for a `thread_ts` (Slack `conversations.replies`). The
  model already has `channel` + `thread_ts` from the seed envelope,
  so it can call this directly to pull the alert / question it's
  replying to.
- **`@posthog/slack-read-channel`** — recent top-level messages in a
  channel, for the rarer "what's been happening here" case.

Both need `channels:history` + `groups:history` bot scopes (already
in the scope list at step 1.3) and the bot to be a member of the
channel. No new secret — they use the same `SLACK_BOT_TOKEN`. When a
user describes a "read the thread to understand the question" flow,
wire `@posthog/slack-read-thread` and confirm the history scopes are
present.

## Common failure modes

| Symptom (user sees)                                                                                | Likely cause                                                                                                                                                             | Fix                                                                                                                                                                                                               |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| URL verification fails BEFORE promote                                                              | Agent has no live revision yet — Slack's challenge POST hits a 404                                                                                                       | Don't paste the URL into Slack until promote returns `state=live`                                                                                                                                                 |
| URL verification fails AFTER promote ("didn't respond")                                            | Tunnel not running / wrong URL / agent-ingress crashed                                                                                                                   | Check `curl <events_url>` from terminal; restart `bin/agent-tunnel`                                                                                                                                               |
| URL turns green but bot doesn't respond to mentions                                                | Bot not invited to channel OR `app_mentions:read` scope missing OR `trusted_workspaces` wrong                                                                            | Invite bot, re-install app, fix `trusted_workspaces`                                                                                                                                                              |
| `invalid_signature` 401 in ingress logs                                                            | `SLACK_SIGNING_SECRET` value mismatch (wrong app, or copied with whitespace)                                                                                             | Rotate via punch-out with `mode: "rotate"`                                                                                                                                                                        |
| `slack.chat.postMessage error: invalid_auth` in session                                            | `SLACK_BOT_TOKEN` revoked or wrong (e.g. `xoxp-` user token vs `xoxb-` bot token)                                                                                        | Rotate via punch-out — confirm it's the Bot User OAuth Token, not the user token                                                                                                                                  |
| `slack.chat.postMessage error: not_in_channel`                                                     | Bot not invited to the target channel                                                                                                                                    | `/invite @<bot>` in the channel                                                                                                                                                                                   |
| Promote refuses with `missing required encrypted_env`                                              | One of the two punch-outs got skipped or `user_cancelled`                                                                                                                | Run that specific `set_secret` again                                                                                                                                                                              |
| Bot ignores thread replies after the first @-mention                                               | `mention_only: true` set without `auto_resume_threads: true`                                                                                                             | Add `auto_resume_threads: true` to the slack trigger config OR drop `mention_only`                                                                                                                                |
| Bot reacts to non-mention messages despite `mention_only`                                          | Slack event subscriptions include `message.channels` AND `auto_resume_threads: true` with the message landing in an owned thread                                         | Expected — `auto_resume_threads` accepts thread replies on owned sessions; the seed flags `mention: false` so the model can ignore                                                                                |
| Bot replies "only the person who started this thread can continue it" to a colleague               | `allow_workspace_participants: false` (default) — a non-owner posted into someone else's thread; the message is parked as an elevation request                           | Expected for owner-only threads. If colleagues should be able to chime in, set `allow_workspace_participants: true` on the slack trigger config                                                                   |
| No `:eyes:` ack reaction lands in Slack                                                            | `ack_reaction` unset, or `SLACK_BOT_TOKEN` missing `reactions:write` scope, or bot not in channel                                                                        | Add the scope + re-install; verify token; remember `ack_reaction` is fail-open so this never blocks ingestion                                                                                                     |
| `ack_reaction_failed` with `slack_error: missing_scope` in ingress logs                            | Bot token lacks `reactions:write`. Slack issues scopes at install time — adding the scope to the app config later requires a re-install to mint a token that carries it. | OAuth & Permissions → add `reactions:write` to Bot Token Scopes → click the yellow "Reinstall to Workspace" banner → authorize. Same `xoxb-...` token now carries the scope; no PostHog-side re-punch-out needed. |
| DM to the bot does nothing (ingress logs `dropped: 'dm_not_enabled'`, or no Messages tab in Slack) | `allow_direct_messages` not set on the slack trigger, OR the app wasn't reinstalled after enabling it (missing `im:history` + Messages tab)                              | Set `allow_direct_messages: true`, regenerate the manifest, re-import it, and reinstall the app so `im:history`/`mpim:history` mint and the App Home Messages tab turns on                                        |

## Things not to do

- **Don't hand the user the Request URL before promote.** Slack's
  verification will fail (no live revision) and the user will retry
  3-4 times before either of you realizes why. Promote first, URL
  second — this is the entire reason this skill is structured the
  way it is.
- **Don't tell the user we use a "team Slack integration".** We
  don't. Each agent's Slack creds live in its own `encrypted_env`.
- **Don't ask for the token values in chat.** Every bot token /
  signing secret comes in through the `set_secret` punch-out — see
  the `secrets-and-integrations` playbook for the hard rule. A Slack agent
  that acts on a service as the user needs an identity provider — see
  the `authenticating-as-the-user` playbook.
- **Don't invent the events URL.** It comes from
  `posthog__agent-applications-retrieve.slack_events_url`. If that field is
  null, the deployment isn't externally reachable — say so and
  stop.
- **Don't promote before both secrets are set** unless the user
  asks for the failure to demonstrate the gate. The error is
  recoverable but adds a wasted turn.
