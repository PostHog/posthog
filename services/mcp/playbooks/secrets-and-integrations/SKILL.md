# Skill — secrets and integrations

How to wire credentials without ever seeing them, and how to tell
the user where to enter what.

## The hard rule

**You never see raw secret values.** Not in chat, not in tool
calls, not by mistake. If the user pastes an API key into the
conversation, you:

1. Tell them not to ("That's an API key — please don't paste it
   into chat. Use the secret form instead.").
2. Don't acknowledge what the key looked like, don't try to set
   it via `set-env-create` (which would put it in your tool-call
   history).
3. Trigger the punch-out flow (below) so they enter it in a
   PostHog UI form instead.
4. Recommend rotating the key they just pasted, since chat
   history may be retained.

## Three distinct concepts

People conflate these. Be precise.

| Concept          | Scope           | Where it lives                             | How to set                                                          |
| ---------------- | --------------- | ------------------------------------------ | ------------------------------------------------------------------- |
| **Secret**       | Per-application | `agent_application.encrypted_env` (Fernet) | Punch-out form OR `agent-applications-set-env-create` (raw — avoid) |
| **Integration**  | Per-team        | `posthog_integration` (OAuth tokens)       | Team admin installs via PostHog integrations UI                     |
| **Trigger auth** | Per-trigger     | `spec.triggers[].auth.modes`               | Edit on the draft revision; controls who can invoke the agent       |

A Slack-posting agent needs Slack **secrets** (`SLACK_SIGNING_SECRET` +
`SLACK_BOT_TOKEN`) on the agent — not a team integration. Each agent
brings its own Slack app + bot token. A Stripe-querying agent likewise
needs a Stripe **secret** on the agent. Integrations are for systems
that legitimately want one workspace-level OAuth connection many agents
share (e.g. some PostHog data sources). When in doubt: it's a secret.

Secrets split further by **who declares the name**:

- **Author-declared** (`spec.secrets[]`) — the agent's tools read
  these (e.g. `STRIPE_API_KEY`, `OPENAI_API_KEY`). The author picks
  the name. Validation surfaces "secret X is declared but not set"
  at freeze time so you know to drive a punch-out before promote.
- **Trigger-required** (`TRIGGER_REQUIRED_SECRETS` registry) — the
  platform picks the name. The author never types it. Today this
  is `SLACK_SIGNING_SECRET` for `slack` triggers (verifies inbound
  Slack signature). See the next section.

## Trigger-required secrets

Some triggers require entries in `encrypted_env` that the spec
doesn't list explicitly. The contract lives in the platform-wide
`TRIGGER_REQUIRED_SECRETS` registry (`spec_schema.py` Django-side,
`services/agent-shared/src/spec/trigger-secrets.ts` runner-side), so
authors don't pick the names and the platform can't drift on what a
trigger consumes.

Current registry:

| Trigger type | Required keys                             | What each is                                                                                                                                   |
| ------------ | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `slack`      | `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN` | App signing secret (verifies inbound webhooks) + bot user OAuth token (lets `@posthog/slack-post-message` etc. call the Slack API as the bot). |
| `chat`       | (none)                                    |                                                                                                                                                |
| `webhook`    | (none)                                    |                                                                                                                                                |
| `cron`       | (none)                                    |                                                                                                                                                |
| `mcp`        | (none)                                    |                                                                                                                                                |

`SLACK_SIGNING_SECRET` lives at Slack app dashboard → Settings → Basic Information → Signing Secret.
`SLACK_BOT_TOKEN` lives at Settings → Install App → Bot User OAuth Token (starts with `xoxb-`), generated when the app is installed to a workspace.

**Enforcement** — the `promote` endpoint walks the spec's triggers
and refuses with a clear error if any required key is missing:

> Cannot promote: agent is missing required encrypted_env entries:
> SLACK_BOT_TOKEN (for slack trigger). Set the value(s) via
> the env editor then retry.

You can recover from this by setting the key and re-running
promote — but a better user experience is to catch it during
**Phase 4** of the `authoring-new-agents` playbook: as soon as the spec
declares a `slack` trigger, drive the punch-out for BOTH required
keys before reaching freeze. See the `setting-up-slack-app` playbook for
the step-by-step flow (create app → set Request URL → install →
copy + punch-out tokens). PostHog Code's env editor also surfaces
"Required for this trigger" hints next to the relevant fields, so a
user setting things up in the UI sees the requirement without you
having to spell it out.

The punch-out call shape is the same as any other secret — pass
the key the registry names:

```text
set_secret { agent_slug: "<slug>", secret: "SLACK_SIGNING_SECRET",
             purpose: "Verifies inbound Slack event signatures." }

set_secret { agent_slug: "<slug>", secret: "SLACK_BOT_TOKEN",
             purpose: "Lets the agent call Slack APIs as the bot user." }
```

After each save, an `env-keys-get` precheck confirms the write
landed. Then proceed to freeze + promote.

> Note: the platform does **not** fall back to a team-wide Slack
> OAuth integration. Each agent owns its own Slack app and bot
> token via `encrypted_env`. If a user pastes a workspace-wide
> Slack bot token they want shared across agents, save it on each
> agent individually — there is no shared store.

## Setting a secret — the punch-out flow

The punch-out flow is live in PostHog Code. You never see the
value; the user enters it into a UI form scoped to that key. Three
paths, picked by what the client supports — preferred to least.

### Path A (preferred) — `client.kind = posthog-code`, inline tool

PostHog Code fulfills a `set_secret` client tool by rendering an
inline form **inside the matching tool-call card**, right in the
chat transcript. The user fills it in without leaving the
conversation.

`set_secret` is an **interactive** client tool — the platform's
park + wake pattern (`spec.tools[].interactive: true`). It behaves
differently from a normal tool, and you need to read the rest of
this section before invoking it. TL;DR: your call returns a
`queued` envelope synchronously, you end the turn, the user
responds on their own time, and on a fresh turn you receive a
wake message with the real outcome.

Loop:

1. **Check current state** with `posthog__agent-applications-env-keys-get`
   `{ id: "<slug>", key: "ANTHROPIC_KEY" }` — returns `{ key, is_set }`.
   If already set and the failure mode suggests the value is wrong,
   pass `mode: "rotate"`; otherwise omit / `mode: "set"`.
2. **Invoke `set_secret`** with `{ agent_slug, secret, mode?, purpose? }`:
   - `agent_slug` is required — pull it from `get_context` (bare) or from
     the agent the user is configuring. Do NOT assume "the agent on
     screen" — the user may navigate while the form is up.
   - `purpose` is a one-line hint shown above the input. Keep it
     factual ("Used for the daily summary call"), no value hints.
3. **The tool result is immediate and synthetic.** You will receive
   a JSON envelope like
   `{ "queued": true, "interactive": true, "call_id": "<uuid>", "tool_id": "set_secret", "message": "Awaiting user input. The result will arrive on the next turn — end this turn now." }`.
   That is NOT the user's answer — it's the platform telling you the
   form has been mounted and the runner has parked the session.
4. **End the turn cleanly.** Acknowledge briefly in plain text
   ("I've put up a form for you to enter the value.") and stop.
   The model that keeps emitting tool calls after seeing a
   `queued: true` envelope wastes turns; do not retry, do not
   poll, do not call `env-keys-get` again.
5. **Wait for the wake.** The session is parked — your worker
   slot is freed and the user has unbounded time to respond. When
   they submit (or cancel), a fresh turn starts and the very first
   `user` message you see carries an envelope like
   `{ "call_id": "<the same uuid>", "ok": true, "result": { "key": "ANTHROPIC_KEY", "action": "set" } }`
   on success or `{ "call_id": "...", "ok": false, "error": "user_cancelled" }` on cancel
   / failure. Match by `call_id` to be safe.
6. **Continue** with whatever you were doing. On `ok: true` no
   need to re-check `env-keys-get`; the wake envelope confirms the
   write landed. On `ok: false` with `error: "user_cancelled"`,
   tell the user the form was cancelled and ask whether they want
   to retry. On any other error, surface the error text and
   suggest the user retry or use the deep-link fallback (Path B).

If the runtime returns `unhandled_client_tool` _immediately_ (older
PostHog Code version that doesn't yet know `set_secret`), fall through
to path B — the runner returns the unhandled error directly, no
park + wake.

### Path B — `client.kind = posthog-code`, deep link

When the inline tool isn't available, hand the user a link to the
secrets editor and wait for a session callback. Loop:

1. Same `env-keys-get` precheck.
2. **Hand the user a link** to the editor:

   ```text
   /agents/<slug>/connections?edit_secret=<KEY>&callback_session=<this session id>
   ```

   `<this session id>` comes from `get_context`. Render
   as markdown: `[Set ANTHROPIC_KEY](/agents/...)`. Don't use a
   `focus_*` tool for this — the editor wants its own modal,
   not a panel hand-off.

3. **Wait for the callback.** When the user saves, PostHog Code
   posts a `[system]` message into the same session:
   `[system] User set secret KEY on agent SLUG. Continue.` Don't
   poll — the callback is push, not pull. If the user closes the
   dialog without saving, ask once after a turn of silence then
   drop it.

### Path C — non-PostHog-Code client

No inline tool, no callback wire — same URL, but you ask the user
to confirm manually. Loop:

1. Same `env-keys-get` precheck.
2. **Generate the absolute URL** (host comes from the user's
   PostHog instance; if you don't know, give the path and let them
   prepend the host themselves):

   ```text
   https://<host>/project/<team>/agents/<slug>/connections?edit_secret=<KEY>
   ```

   Omit `callback_session=` — without PostHog Code there's nothing
   to receive it.

3. Tell them: "Open <url>, set your value, then say 'done' here."
4. When they say done, **verify** with `env-keys-get` before
   continuing. The user may have closed the tab without saving.

### When to use `agent-applications-set-env-create` directly

Almost never. The raw API exists for CI / scripts that already
hold the value in a variable. Using it from chat puts the value
in your tool-call history → it'd be in the session trace
indefinitely → that's a leak even though it's encrypted at rest.
The only exception is when the user has explicitly told you to
("I have it in 1Password and the punch-out form is broken, here's
the value — set it once and we'll rotate it after"), and even
then warn them about the trace before complying.

## Connecting a third-party service

There is no `spec.integrations[]` field. For a third-party service
the agent should call:

- **MCP server** — connect it once (OAuth/DCR or api-key) and
  reference it with `mcps[].connection`; every asker of the agent
  shares that one owner-connected credential.
- **Per-asker OAuth** — wire an `identity_providers[]` entry plus an
  `auth.provider` on the MCP/tool so each asker authenticates as
  themselves. See `skills/authenticating-as-the-user`.

> Slack is **not** one of these. Use `SLACK_BOT_TOKEN` +
> `SLACK_SIGNING_SECRET` on the agent's `encrypted_env` via the
> punch-out flow. See the `setting-up-slack-app` playbook.

## Rotating a secret

Standard flow:

1. User updates the underlying provider (rotates the Stripe key,
   etc.).
2. You drive the same punch-out flow as Path A above, but invoke
   `set_secret` with `mode: "rotate"` (the `env-keys-get` precheck
   will show the key is already set). The user enters the new value
   in the inline form.
3. The next session opened uses the new value (the runner reads
   it at session start, not at agent-define time).

In-flight sessions keep the old value until they end — the
secret is resolved once per session.

## When a tool call fails because of auth

Common patterns:

- `provider_error: invalid_api_key` — the secret is wrong / expired
- A raw Slack error like `invalid_auth` from `@posthog/slack-post-message`
  — the agent's `SLACK_BOT_TOKEN` is wrong or revoked
- `403 Forbidden` from the PostHog MCP — the user's principal
  doesn't have the scope (`agent_application:write` etc.)

Don't try to "retry with different auth". Surface the failure:

> The `@posthog/slack-post-message` call failed with
> `slack.chat.postMessage error: invalid_auth`. The agent's
> `SLACK_BOT_TOKEN` is wrong or revoked — rotate it via the
> punch-out and the next session will pick up the new value.

## Things not to do

- **Don't suggest hardcoding a secret in `agent.md` or a custom
  tool.** Plaintext secrets leak into model context AND don't
  benefit from rotation. Always `spec.secrets[]` + nonce-substitution
  at session start.
- **Don't suggest disabling auth.** "Add `public` to a trigger's
  `auth.modes` to fix the 401" is almost always wrong. Find the auth
  bug; don't remove the lock.
- **Don't infer integration state.** If a Slack call fails, you
  can't tell from your side whether the integration is broken or
  the call was malformed. Ask the user to check the integrations
  page.
- **Don't paste env state to the user.** If you ever do see the
  `encrypted_env` field by mistake (you shouldn't, the MCP
  shouldn't return it), don't relay it.

## Quick reference — what each error means

| Symptom                                                 | Cause                                         | Action                                                                       |
| ------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------- |
| `validate_error: missing_secret`                        | `spec.secrets[]` has a name with no value set | Trigger punch-out for that key                                               |
| `provider_error: invalid_api_key`                       | The secret value is wrong                     | Trigger punch-out + tell user the previous value was rejected                |
| Slack `invalid_auth` from `@posthog/slack-post-message` | `SLACK_BOT_TOKEN` wrong / revoked             | Rotate `SLACK_BOT_TOKEN` via the punch-out; next session picks it up         |
| `403` from the PostHog MCP                              | User's principal scope insufficient           | Surface the missing scope; user gets it via OAuth re-auth or asking an admin |
| `set-env-create` succeeds but agent still fails         | Old session in flight using old value         | Wait for in-flight sessions to drain; new sessions get the new value         |
