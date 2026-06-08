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

| Concept         | Scope           | Where it lives                             | How to set                                                          |
| --------------- | --------------- | ------------------------------------------ | ------------------------------------------------------------------- |
| **Secret**      | Per-application | `agent_application.encrypted_env` (Fernet) | Punch-out form OR `agent-applications-set-env-create` (raw — avoid) |
| **Integration** | Per-team        | `posthog_integration` (OAuth tokens)       | Team admin installs via PostHog integrations UI                     |
| **Spec.auth**   | Per-application | `spec.auth.mode`                           | Edit on the draft revision; controls who can invoke the agent       |

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
**Phase 4** of `skills/authoring-new-agents`: as soon as the spec
declares a `slack` trigger, drive the punch-out for BOTH required
keys before reaching freeze. See `skills/setting-up-slack-app` for
the step-by-step flow (create app → set Request URL → install →
copy + punch-out tokens). The console env editor also surfaces
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

The punch-out flow is live in the agent console. You never see the
value; the user enters it into a UI form scoped to that key. Three
paths, picked by what the client supports — preferred to least.

### Path A (preferred) — `client.kind = agent-console`, inline tool

The console fulfills a `set_secret` client tool by rendering an
inline form **inside the matching tool-call card**, right in the
chat transcript. The user fills it in without leaving the
conversation. Loop:

1. **Check current state** with `agent-applications-env-keys-get`
   `{ id: "<slug>", key: "ANTHROPIC_KEY" }` — returns `{ key, is_set }`.
   If already set and the failure mode suggests the value is wrong,
   pass `mode: "rotate"`; otherwise omit / `mode: "set"`.
2. **Invoke `set_secret`** with `{ agent_slug, secret, mode?, purpose? }`:
   - `agent_slug` is required — pull it from `get_context` or from
     the agent the user is configuring. Do NOT assume "the agent on
     screen" — the user may navigate while the form is up.
   - `purpose` is a one-line hint shown above the input. Keep it
     factual ("Used for the daily summary call"), no value hints.
3. **Wait.** The tool resolves with `{ key, action: "set" }` on
   success, `{ error: "user_cancelled" }` if they cancel, or a
   string error on a save failure. Don't add chatter while the
   user is mid-form — they can see what's happening.
4. **Continue** with whatever you were doing. No need to re-check
   `env-keys-get`; the tool's success result already confirms the
   write landed.

This path is the default for `client.kind = agent-console`. If the
runtime returns `unhandled_client_tool` (an older console version
that doesn't yet know `set_secret`), fall through to path B.

### Path B — `client.kind = agent-console`, deep link

When the inline tool isn't available, hand the user a link to the
secrets editor and wait for a session callback. Loop:

1. Same `env-keys-get` precheck.
2. **Hand the user a link** to the editor:

   ```text
   /agents/<slug>/connections?edit_secret=<KEY>&callback_session=<this session id>
   ```

   `<this session id>` comes from `@posthog/ui/get_context`. Render
   as markdown: `[Set ANTHROPIC_KEY](/agents/...)`. Don't use
   `@posthog/ui/focus` for this — the editor wants its own modal,
   not a panel hand-off.

3. **Wait for the callback.** When the user saves, the console
   posts a `[system]` message into the same session:
   `[system] User set secret KEY on agent SLUG. Continue.` Don't
   poll — the callback is push, not pull. If the user closes the
   dialog without saving, ask once after a turn of silence then
   drop it.

### Path C — non-console client

No inline tool, no callback wire — same URL, but you ask the user
to confirm manually. Loop:

1. Same `env-keys-get` precheck.
2. **Generate the absolute URL** (host comes from the user's
   PostHog instance; if you don't know, give the path and let them
   prepend the host themselves):

   ```text
   https://<host>/project/<team>/agents/<slug>/connections?edit_secret=<KEY>
   ```

   Omit `callback_session=` — without the console there's nothing
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

## Setting an integration

For systems that DO use team integrations (not Slack), you don't
set them — the team admin does, via PostHog's integrations UI.
You can:

- Check whether an integration is installed by reading the team's
  integrations from PostHog. (No dedicated MCP tool for this today
  — surface as a known gap, ask the user to confirm in the UI.)
- Reference an integration in `spec.integrations[]`. The runner
  resolves it at session start.
- Tell the user "this agent needs an X integration on this team; an
  admin can install it at <link>" — the link is a PostHog URL the
  user follows manually.

> Slack is **not** one of these. Use `SLACK_BOT_TOKEN` +
> `SLACK_SIGNING_SECRET` on the agent's `encrypted_env` via the
> punch-out flow. See `skills/setting-up-slack-app`.

## Rotating a secret

Standard flow:

1. User updates the underlying provider (rotates the Stripe key,
   etc.).
2. User triggers the punch-out form (you call
   `agent-applications-secrets-issue-write-token`) and enters the
   new value.
3. The next session opened uses the new value (the runner reads
   it at session start, not at agent-define time).

In-flight sessions keep the old value until they end — the
secret is resolved once per session.

## When a tool call fails because of auth

Common patterns:

- `provider_error: invalid_api_key` — the secret is wrong / expired
- `gateway_unavailable` on the Slack integration — the integration
  was revoked
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
- **Don't suggest disabling auth.** "Change `spec.auth.mode` to
  `public` to fix the 401" is almost always wrong. Find the auth
  bug; don't remove the lock.
- **Don't infer integration state.** If a Slack call fails, you
  can't tell from your side whether the integration is broken or
  the call was malformed. Ask the user to check the integrations
  page.
- **Don't paste env state to the user.** If you ever do see the
  `encrypted_env` field by mistake (you shouldn't, the MCP
  shouldn't return it), don't relay it.

## Quick reference — what each error means

| Symptom                                         | Cause                                         | Action                                                                       |
| ----------------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------- |
| `validate_error: missing_secret`                | `spec.secrets[]` has a name with no value set | Trigger punch-out for that key                                               |
| `provider_error: invalid_api_key`               | The secret value is wrong                     | Trigger punch-out + tell user the previous value was rejected                |
| `gateway_unavailable: integration_revoked`      | OAuth token expired / revoked                 | Tell user to re-install integration                                          |
| `403` from the PostHog MCP                      | User's principal scope insufficient           | Surface the missing scope; user gets it via OAuth re-auth or asking an admin |
| `set-env-create` succeeds but agent still fails | Old session in flight using old value         | Wait for in-flight sessions to drain; new sessions get the new value         |
