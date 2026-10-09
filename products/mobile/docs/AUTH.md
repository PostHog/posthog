# Auth

The app signs in with OAuth 2.0 authorization code + PKCE as a public client.
Code: `src/auth/` (flow, store, tokens), `src/api/users.ts` (bootstrap), `src/api/client.ts` (bearer + refresh on 401).

## Flow

```text
Sign in ──► AuthRequest (PKCE S256, state) ──► system browser: {host}/oauth/authorize
                                                  │ user signs in (first-party apps skip consent)
            posthog://callback?code&state ◄───────┘
   ──► state check (expo-auth-session) ──► POST {host}/oauth/token (JSON, code + code_verifier)
   ──► GET /api/users/@me/ ──► GET /api/organizations/{id}/ for each other organization
   ──► tokens to the secure store, account to AsyncStorage ──► status signed_in ──► /inbox
```

- The authorize page opens in the system browser (`openAuthSessionAsync`), so it shares cookies with the user's browser.
  A user already signed in to PostHog there only confirms.
- The grant is not narrowed to one project (no `required_access_level`), so the project switcher lists every project.
- `restore()` runs once at boot from `app/_layout.tsx`.
  Screens mount only after it finishes, so no query runs without a token.
  It refreshes first when the access token has less than a minute left.
- Any request that gets a 401 refreshes once and retries (`src/api/client.ts`).
  Concurrent 401s share one refresh, because each refresh rotates the token.
- A refresh rejected with 400, 401 or 403 ends the session: tokens and the query cache are cleared and every screen goes to sign in, which says the session ended.
  A network error or 5xx keeps the session; the request fails and the next one tries again.
- Sign out unregisters the push token, revokes the refresh token (`POST {host}/oauth/revoke`, form body, `client_id`), then clears tokens, the query cache and the analytics identity.
  Revocation failures are ignored, so sign out works offline.
- On Android the callback also arrives as a deep link. `app/+native-intent.tsx` drops it so Expo Router does not open an unmatched `/callback` screen.

## Hosts and client ids

| Region | Host | Client id |
| --- | --- | --- |
| US | `https://us.posthog.com` | `a5TY7w9IjFYfes6dkPgZe6envclWw3bm2UD8ZTlm` |
| EU | `https://eu.posthog.com` | `1A7vO138Fh5sYmJislicN4F5HnttI6urmFttxPDU` |
| Custom | typed by the user | defaults to `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ` (the local dev app), editable |

Redirect URI: `posthog://callback` (`makeRedirectUri({ scheme: 'posthog', path: 'callback' })`).
Expo Go produces an `exp://` redirect that no app registers, so sign in needs a development build.

Custom hosts must be https. Plain http is accepted only for loopback (`localhost`, `127.0.0.0/8`, `::1`), which is also the only place the server allows http redirects.

## Scopes

The app requests exactly these scopes (`OAUTH_SCOPES` in `src/auth/oauth.ts`):

`openid profile email user:read user:write organization:read project:read task:read task:write conversation:write today:read`

| Scope | Used by |
| --- | --- |
| `user:read` | `GET /api/users/@me/` |
| `user:write` | push token register and unregister |
| `organization:read` | `GET /api/organizations/{id}/` for the project list |
| `project:read` | project-scoped reads |
| `task:read`, `task:write` | reports, hand-off, runs, notification routing |
| `conversation:write` | chat |
| `today:read` | `GET today/briefing/` and `GET today/reports/{id}/page/`. Without it both return 403 and the inbox always falls back to the signals report list. |

### Server-side ceiling

Each OAuth application has a scope ceiling: `OAuthApplication.scopes` plus `optional_scopes` (`posthog/models/oauth.py`).
An empty ceiling, or one containing `@default`, allows every unprivileged scope; any other ceiling is an exact allow-list.
The production app rows are not visible from this repository, so check them in Django admin when the app adds a scope.

- `/authorize` normally does not reject an out-of-ceiling scope. It drops it and issues the rest, so the usual symptom is a 403 on the feature that needs it, for example the inbox never showing the Today briefing.
- When the server does answer `invalid_scope` (on the authorize redirect or the token endpoint), the sign-in screen says "This app's OAuth registration is missing a permission. Ask an admin to update it."

Either way the fix is the same: add the scope to the mobile OAuth application's `scopes` in Django admin (or set the ceiling to `@default`), then sign in again.

## Token lifetimes

From `OAUTH2_PROVIDER` in `posthog/settings/web.py` and `OAuthValidator` in `posthog/api/oauth/views.py`:

- Access token: 7 days for first-party and dynamically registered clients, 1 hour for every other client.
- Refresh token: 30 days, rotated on every refresh. Reusing an old refresh token after the 2 minute grace period revokes the whole token family.
- Authorization code: 5 minutes.

## Storage

| What | Where |
| --- | --- |
| Access token, refresh token, expiry | `expo-secure-store` key `posthog_mobile_session` |
| Region, host, client id, user, organizations, projects, current project | AsyncStorage key `posthog-mobile-auth` (zustand `persist`) |
| Web build | localStorage in dev builds, memory in release builds (a reload signs out) |

Region, host and client id stay after sign out so the sign-in form starts where the user left it.

## Store shape

`useAuthStore` (`src/auth/authStore.ts`):

| Field | Meaning |
| --- | --- |
| `status` | `loading` until `restore()` finishes, then `signed_out` or `signed_in` |
| `signedIn` | `status === 'signed_in'` |
| `region`, `host`, `clientId`, `method` | the session's instance and how it signed in (`oauth` or `personal_api_key`) |
| `user` | `{ uuid, distinctId, email, name }` |
| `organizations` | `{ id, name }[]` |
| `projects` | `{ id, name, organizationId, organizationName }[]`, current organization first |
| `projectId`, `projectName` | the current project; `projectPath()` reads `projectId` |
| `accountLoading`, `accountError` | the last account reload |
| `signedOutReason` | `expired` when the server ended the session |

Actions: `restore()`, `signIn(host, clientId)`, `signInWithPersonalApiKey(host, key)`, `selectProject(id)`, `reloadAccount()`, `signOut()`.
`selectProject` resets every TanStack query, so no screen shows the previous project's data.
`addSignOutTask(task)` registers work that needs the token during sign out (push unregistration uses it).

## Development sign in

- **Local stack.** Run `python manage.py setup_tasks_oauth` in the main checkout.
  It creates the dev app `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ` with `posthog://callback` among its redirect URIs.
  In the app pick Custom, enter `http://localhost:8010`, keep the default client id.
  The dev app is not first-party, so the consent screen shows and access tokens last 1 hour, which exercises refresh often.
  - iOS simulator: `localhost` reaches the Mac.
  - Android emulator: run `adb reverse tcp:8010 tcp:8010` first, so `localhost` on the emulator reaches the Mac.
- **Personal API key** (dev builds only, `__DEV__`). Tap "Use a personal API key", pick the region or a custom host, paste a key with `user:read`, `organization:read`, `project:read` and the scopes of the screens you test (`task:read`, `task:write`, `user:write`, `conversation:write`).
  The key never refreshes; a 401 ends the session.
- **Demo.** "Try the demo" needs no account.

## Register a new OAuth app

For a self-hosted instance or a new environment, create the app in Django admin (`/admin/posthog/oauthapplication/add/`):

| Field | Value |
| --- | --- |
| Name | PostHog mobile |
| Client type | Public |
| Authorization grant type | Authorization code |
| Redirect URIs | `posthog://callback` |
| Algorithm | RS256 |
| Is first party | On only for apps PostHog ships. It skips the consent screen and gives 7 day access tokens. |
| Scopes | Leave empty or `@default`, or list every scope above as the ceiling |

Copy the generated client id into the Custom client id field on the sign-in screen.

## Manual test

A real OAuth sign in cannot run in CI. Before a release, on a development build:

1. Sign in on US with a PostHog account. Check that the system browser opens, returns to the app and lands on the inbox.
2. Settings shows the host, your email and every project grouped by organization. Switch project and check the inbox reloads.
3. Kill and reopen the app. It opens on the inbox without signing in again.
4. Cancel the browser during sign in. The sign-in screen says it was canceled and offers Try again.
5. Turn on airplane mode and reopen the app. The app stays signed in and shows load errors with Try again.
6. Against a local stack, delete the session's refresh and access token rows in Django admin (OAuth refresh tokens, OAuth access tokens), then pull to refresh. The app returns to sign in and says the session ended. First-party apps do not appear under Connected apps, so this needs admin.
7. Sign out from Settings. Confirm, then check that sign in comes back and a second launch stays signed out.
8. Repeat 1 on EU, and once against a local stack (see above).
