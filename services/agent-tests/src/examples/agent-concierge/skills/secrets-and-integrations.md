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

A Slack-posting agent needs a Slack **integration**, not a secret.
A Stripe-querying agent needs a Stripe **secret**, not an
integration. Don't mix them up.

## Setting a secret — the punch-out flow

> **Status note:** the punch-out flow is designed in
> `agent-authoring-flow.md` §3 phase 3 but **not yet shipped**.
> Today the only way to set a secret is `agent-applications-set-env-create`
> with the raw value, which violates rule #1 above. Until the
> punch-out endpoints exist, tell the user to set the secret
> themselves via the PostHog UI (Settings → Project → Agent
> applications → <slug> → Env) and confirm via the spec-side
> reflection of `is_set` once the platform exposes it.

When the punch-out flow ships, the loop is:

1. Call `agent-applications-secrets-issue-write-token` with the
   application id and the key name(s).
2. The server returns `{ url, expires_at }`. The URL is a signed
   one-time link to a PostHog form scoped to those keys only.
3. Tell the user: "Please open <url> and enter your <key name>.
   I'll continue once that's set."
4. Poll `agent-applications-secrets-status` every 5-10s. When
   `is_set: true` for every required key, continue.

Never put the URL itself behind an `@posthog/ui/focus` — open in a
new tab, never the read panel, since the form is sensitive.

## Setting an integration

You don't. The team admin does, via PostHog's integrations UI.
You can:

- Check whether an integration is installed by reading the team's
  integrations from PostHog. (No dedicated MCP tool for this today
  — surface as a known gap, ask the user to confirm in the UI.)
- Reference an integration in `spec.integrations[]`. The runner
  resolves it at session start.
- Tell the user "this agent needs a Slack integration on this
  team; an admin can install it at <link>" — the link is a
  PostHog URL the user follows manually.

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
> `gateway_unavailable: integration_revoked`. The Slack
> integration for this team needs to be re-authorized — a team
> admin can do this at <link>. Once that's done, the next
> session will pick up the new token.

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
