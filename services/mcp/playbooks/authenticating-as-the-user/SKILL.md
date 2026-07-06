# Skill — authenticating as the user (the identity system)

Load this whenever you wire an agent that calls PostHog or any
third-party API **as the user** — adding an MCP with `auth.provider`,
giving a tool that acts on the user's behalf, choosing OAuth scopes, or
when the user asks about connecting / linking / OAuth / "act as me". This
is the whole model end to end; get it right and the agents you build can
safely do work on a real person's behalf.

## Two axes — keep them separate

Identity has two independent questions. Confusing them is the #1 mistake.

1. **Principal — _who is asking?_** Set by the trigger:
   - `posthog` (chat / MCP): an authenticated PostHog user — the bearer
     arrives at the trigger edge (the PostHog Code / IDE passthrough).
   - `slack`: a Slack user (identified by their Slack user id).
   - `jwt`: an embedding app's end-user.
     The principal is _who_, not _what they can do_.

2. **Credential provider — _how does the agent act as them on a service?_**
   Declared in `spec.identity_providers[]`. A provider turns the principal
   into a usable bearer for one service (PostHog, GitHub, Linear, …).

A tool or MCP says "I need to act as the user on service X" by naming a
provider. The runtime then resolves the asking principal → that provider's
credential. Same shape for PostHog and for a bring-your-own API.

## `spec.identity_providers[]`

Two kinds:

- **`kind: "posthog"`** — the managed PostHog provider. You declare it with
  just `scopes`; on promote the backend provisions a normal (user-consented)
  OAuth app and injects its `client_id`. Use this for any agent that calls
  PostHog as the user.

  ```json
  { "kind": "posthog", "scopes": ["openid", "profile", "email", "user:read", "query:read", "insight:read"] }
  ```

- **`kind: "oauth2"`** — bring-your-own provider (GitHub, Linear, an internal
  API). You supply the endpoints + client:

  ```json
  {
    "kind": "oauth2",
    "id": "github",
    "authorize_url": "https://github.com/login/oauth/authorize",
    "token_url": "https://github.com/login/oauth/access_token",
    "userinfo_url": "https://api.github.com/user",
    "client_id": "...",
    "client_secret_ref": "GITHUB_OAUTH_SECRET",
    "scopes": ["repo", "read:user"]
  }
  ```

  `client_secret_ref` names an `encrypted_env` secret (set it like any other
  secret — see `secrets-and-integrations`).

Both take `binding: "principal"` (default) — the credential is per-asker, "act
as THIS user". (`binding: "agent"`, one shared app credential, is a future
seam — don't use it.)

## How a capability says it needs a provider

- **MCP server:** `"auth": { "provider": "posthog" }` on the `mcps[]` entry.
  The runner stamps the asker's bearer on every request to that MCP. This is
  how the PostHog MCP itself is wired.
- **Native tool:** the tool's own `requires.provider` declares it (you don't
  set this — it's baked into the native tool). PostHog-API native tools resolve
  the posthog provider automatically.
- **Custom tool:** `"requires_identity": "<provider id>"` on the `tools[]` entry
  — the agent is handed an `auth_required` link to relay if the user is unlinked
  (credential injection into the sandbox is a later step).

## What resolution produces — and what the agent does

Every identity-gated call resolves to one of three outcomes:

- **`ok`** — a bearer was available; the call runs as the user.
- **`link_required`** — the user hasn't linked yet. The tool/MCP returns a
  connect link (an `auth_required` payload, or the MCP degrades with one). The
  agent **relays it as a markdown link** ("Connect your PostHog account: [link]"),
  asks the user to click, then retries — it is NOT an error or a dead capability.
- **`unavailable`** — can't link here (e.g. a shared thread, or an
  anonymous principal). Surface plainly.

Where the bearer comes from depends on the surface:

- **chat / MCP (PostHog Code, IDE):** passthrough from the trigger edge —
  already authenticated, no link step.
- **slack:** the user links once via the OAuth flow. After linking it's
  persisted per-user and reused.

**`@posthog/identity-connect`** mints a connect/reconnect link on demand for any
declared provider — use it to proactively hand the user a link ("connect my
PostHog account") rather than waiting for a call to fail. If a linked grant is
later missing a scope the service now requires, the same path offers a
**reconnect** link (re-authorize with the updated scopes).

## Choosing scopes

- Use **explicit OAuth scope objects**, never `*` — `*` is a personal-API-key
  concept and OAuth `/authorize` rejects it (`invalid_scope`).
- Always include the identity scopes `openid profile email` and **`user:read`**
  — the PostHog MCP's first call is `/api/users/@me/`, which needs `user:read`;
  omit it and even read tools fail.
- Add the `:read` / `:write` scopes for exactly the surfaces the agent touches:
  `query:read` + `insight:read` for analytics, `agents:read` + `agents:write`
  for authoring other agents, `feature_flag:read`, `error_tracking:read`, etc.
  The OAuth app's scope ceiling is provisioned from this list, so widening it
  later means a re-promote and a re-link.
- If the user hits a 403 on a surface, the fix is usually an added `:read`
  scope (then re-link), not a workaround. A 403 on a scope they _have_ is their
  account's access speaking — surface it, don't route around it.

## Shared threads fail closed

A Slack trigger with `allow_workspace_participants: true` lets anyone in the
workspace drive an open thread. Identity then **fails closed**: the agent will
not resolve the thread owner's credential to act for a different participant
(that would be a confused-deputy). An agent that acts as the user on a service
must keep `allow_workspace_participants: false` (owner-only) — the asker is the
session owner and only their own identity ever resolves.

## Wiring checklist for an agent that acts on PostHog as the user

1. Add the MCP: `{ "id": "posthog", "url": "<mcp url>", "auth": { "provider": "posthog" } }`.
2. Declare `identity_providers: [{ "kind": "posthog", "scopes": [...] }]` with
   `user:read` + the surfaces it needs. Set it with
   `posthog__agent-applications-revisions-partial-update` (or `…-spec-update` for a
   whole-spec replace); both accept `identity_providers` and an MCP's `auth.provider`.
   `…-revisions-retrieve` afterwards to confirm both landed.
3. If Slack-triggered: `allow_workspace_participants: false`, and tell it in
   `agent.md` to relay the connect link when a call comes back needing one.
4. Validate, freeze, promote — promote provisions the OAuth app. Then the user
   links on first use.
