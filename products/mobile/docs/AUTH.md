# Auth

The app signs in with OAuth 2.0 authorization code + PKCE as a public client.
Code: `src/auth/` (flow, store, tokens), `src/api/users.ts` (bootstrap), `src/api/client.ts` (bearer + refresh on 401).

## Flow

```text
Sign in ──► AuthRequest (PKCE S256, state) ──► system browser: {host}/oauth/authorize
                                                  │ user signs in (first-party apps skip consent)
            {scheme}://callback?code&state ◄──────┘
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
- Sign out waits for the push registration queue, unregisters the device token, revokes the refresh token (`POST {host}/oauth/revoke`, form body, `client_id`), then clears tokens, the query cache and the analytics identity.
  If push unregistration fails, sign out keeps the session and shows a retry action. OAuth revocation failures are ignored after push cleanup succeeds.
- OAuth and personal-key sign-in load the candidate account with its own host and credential. The active host, token and account change together only after that succeeds. A canceled or failed attempt leaves the previous session in place.
- On Android the callback also arrives as a deep link. `app/+native-intent.tsx` drops it so Expo Router does not open an unmatched `/callback` screen.

## Hosts and client ids

| Region | Host | Client id |
| --- | --- | --- |
| US | `https://us.posthog.com` | `a5TY7w9IjFYfes6dkPgZe6envclWw3bm2UD8ZTlm` |
| EU | `https://eu.posthog.com` | `1A7vO138Fh5sYmJislicN4F5HnttI6urmFttxPDU` |
| Self-hosted (`custom` in the store) | typed by the user | internal builds prefill `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ` (the local dev app); store builds start empty. Editable. |

### Redirect URIs

The redirect URI is `{scheme}://callback` (`makeRedirectUri({ scheme: appScheme, path: 'callback' })`).
The scheme follows the variant the native build was made as (see [RELEASING.md](RELEASING.md#build-variants)):

| Build | Redirect URI |
| --- | --- |
| Store build, and any local build without `APP_VARIANT` | `posthog://callback` |
| `APP_VARIANT=preview` | `posthog-preview://callback` |
| `APP_VARIANT=development` | `posthog-dev://callback` |

The scheme comes from the bundle id, not from Metro, so a Metro session in a store-identity build still uses `posthog://callback`.
Every redirect URI a build uses must be registered on the OAuth application it signs in to, or the authorize page rejects the request:

- The US and EU mobile applications need all three URIs for dev and preview builds to sign in to PostHog Cloud. Add the two internal ones in Django admin.
- The local dev app from `setup_tasks_oauth` registers all three callbacks, so an EAS development or preview build signs in to a local stack without a manual edit. A stack set up before that change needs `python manage.py setup_tasks_oauth` run again, which appends the missing URIs.

Expo Go produces an `exp://` redirect that no app registers, so sign in needs a development build.

Self-hosted hosts must be https. Plain http is accepted only for loopback (`localhost`, `127.0.0.0/8`, `::1`), which is also the only place the server allows http redirects, and only in internal builds (dev, preview, or any Metro session).
A store build rejects `http://localhost`.

## Scopes

The app requests exactly these scopes (`OAUTH_SCOPES` in `src/auth/oauth.ts`):

`openid profile email user:read user:write organization:read project:read task:read task:write conversation:write today:read query:read dashboard:read insight:read file_system_shortcut:write`

| Scope | Used by |
| --- | --- |
| `user:read` | `GET /api/users/@me/` |
| `user:write` | push token register and unregister |
| `organization:read` | `GET /api/organizations/{id}/` for the project list |
| `project:read` | project-scoped reads |
| `task:read`, `task:write` | reports, hand-off, runs, notification routing |
| `conversation:write` | chat |
| `today:read` | `GET today/briefing/` and `GET today/reports/{id}/page/`. Without it both return 403 and the inbox always falls back to the signals report list. |
| `query:read` | `POST query/` for the live report metrics and charts, and in Views for web analytics, compare on an insight, and the people and recordings at a chart point. Without it the query returns 403, and the report shows each metric's saved value and series instead. |
| `dashboard:read` | Views: dashboard detail, the dashboard list, search, and the dashboards in Recent |
| `insight:read` | Views: insight reads in every `refresh` mode, the insight list, search, and `POST insights/viewed/`. Chat: cached insight names and descriptions in insight cards. Without it the chat card keeps its browser link and shows that the summary could not load. |
| `file_system_shortcut:write` | Views: pins, which are the web's starred items. It also grants `file_system_shortcut:read` for the pin list. |

### Granted scopes and signing in again

The token response's `scope` is stored with the tokens as `grantedScopes` (`src/auth/tokens.ts`).
A refresh response without `scope` keeps the previous value, because a refresh never widens a grant.
Sessions stored before the app recorded scopes, and personal API keys, have `grantedScopes: null`.
The sign-in also stores the scopes it asked for as `requestedScopes`, and a refresh keeps them.

The Views scopes arrived after the first release, so a user signed in before then has a grant without them.
Nothing signs that user out: the inbox and chats keep working.
`useViewsAccess()` in `src/features/views/useViewsAccess.ts` decides what Views shows:

- `reauth` when the OAuth grant lacks a Views scope, or when a Views request answered 403 with "API key missing required scope". Views then asks the user to sign in again once.
- `unavailable` when the last sign-in asked for that scope and the grant still lacks it. The ceiling below dropped it, so a new sign-in gets the same grant. Views says it isn't available yet and offers no sign-in.
- `personal-key-missing-scopes` for the same cases with a personal API key, which needs the scopes added to the key.
- `ok` otherwise. A `:write` scope counts as its `:read`.

`missingScope(error)` in `src/api/scopeErrors.ts` reads the scope name from that 403, so a 403 for a dashboard the user cannot view stays a row error.

### Server-side ceiling

Each OAuth application has a scope ceiling: `OAuthApplication.scopes` plus `optional_scopes` (`posthog/models/oauth.py`).
An empty ceiling, or one containing `@default`, allows every unprivileged scope; any other ceiling is an exact allow-list.
The production app rows are not visible from this repository, so check them in Django admin when the app adds a scope.

- `/authorize` normally does not reject an out-of-ceiling scope. It drops it and issues the rest, so the usual symptom is a 403 on the feature that needs it, for example the inbox never showing the Today briefing.
- When the server does answer `invalid_scope` (on the authorize redirect or the token endpoint), the sign-in screen says "This app's OAuth registration is missing a permission. Ask an admin to update it."

Either way the fix is the same: add the scope to the mobile OAuth application's `scopes` in Django admin (or set the ceiling to `@default`), then sign in again.

The US and EU client ids are also used by the mobile apps in `products/desktop/apps/mobile` and `products/desktop/apps/mobilehog`, so a ceiling change applies to them too.
On an application that is not first party, every entry in `scopes` is required for every client, so add a new scope to `optional_scopes` there instead.

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
If AsyncStorage cannot be read on launch, the auth routing gate settles with its default signed-out state so the splash screen can close.

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

Actions: `restore()`, `signIn(host, clientId)`, `signInWithPersonalApiKey(host, key)`, `selectProject(id, from)`, `reloadAccount()`, `signOut()`.
`selectProject` resets every TanStack query, so no screen shows the previous project's data.
`addSignOutTask(task)` registers work that needs the token during sign out (push unregistration uses it).

## Sign-in screen

The screen mirrors the web login page: data region, Log in, Try the demo.
Every build shows "Try the demo", including preview and store builds, so app reviewers can try the app without an account.
In a release build it is the only way to start demo mode. Settings there can only leave demo mode, with "Exit demo".
Development bundles (`__DEV__`) also have the Settings demo toggle and start in demo mode with `EXPO_PUBLIC_DEMO_MODE=1`.
Every build restores a saved demo session when the app relaunches.
Log in always opens the system browser, where the user's password, Google, GitHub, GitLab or SSO login happens.
The app never asks for an email or password itself.

The app does not create accounts. The footer link "Create an account" opens `{host}/signup` in the browser for the selected cloud region.
Store review may not allow a link out of the app for sign-up, so a build can hide the link with `EXPO_PUBLIC_SIGNUP_LINK=0`.
The `production` profile in `eas.json` and `pnpm update:production` set it, so store builds hide the link.
Under the card, "Privacy policy" and "Terms" open posthog.com in the browser.

Internal builds show the environment ribbon above the logo, for example "Dev build · US cloud".
It names the selected region, or the self-hosted address once it is valid.
A store build shows it only for a self-hosted address, in red.
The link is also hidden while "Use a self-hosted instance" is selected.

## Analytics

The sign-in, session and settings events never carry the host, the error text or anything typed:

- `mobile_sign_in_started` with `method` (`oauth` or `personal_api_key`), `region` and `after_expiry` (the screen showed "Your session ended").
- `mobile_sign_in_failed` with `method`, `region`, `retryable` and `reason`: an `OAuthErrorKind` (`cancelled`, `denied`, `network`, ...), `invalid_input`, `invalid_key`, `account_rejected`, `account_forbidden`, `account_load` or `unknown` (`signInFailureReason()` in `src/auth/signInErrors.ts`).
- `mobile_signed_in` with `method` and `region`.
- `mobile_sign_in_region_changed` with `region`, from the region pill and "Use a self-hosted instance".
- `mobile_create_account_opened` with `region`.
- `mobile_session_restored` with `method`, once per cold start that opens signed in.
- `mobile_signed_out` with `reason` (`user`, or `expired` when the server ended the session) and `method`. It fires before the analytics identity resets.
- `mobile_account_reload_failed` with `reason` (`forbidden`, `api_error`, `network` or `unknown`).
- `mobile_project_picker_opened`, and `mobile_project_switched` with `from` (`nav_menu`, `settings` or `push`).
- `mobile_settings_opened` with `from` (`nav_menu`).
- `mobile_default_page_changed` with `page` and `previous_page` (`inbox`, `chats` or `views`), when Start page in Settings changes.
- `mobile_default_page_defaulted` with `page` (`inbox` or `views`) and `org_ai_approved`, when the app saves the start page once for a person who never chose one.
- `mobile_sign_out_confirm_shown` and `mobile_sign_out_cancelled` with `from` (`settings` or `nav_menu`).
- `mobile_demo_started` with `from` (`sign_in` or `settings`), and `mobile_demo_ended` with `from` (`settings`, `sign_out`, `sign_in` or `push`).
- `mobile_deep_link_opened` with `path_kind` (the first path segment as an enum, `deepLinkKind()` in `src/lib/deepLinkKind.ts`) and `initial`. `app/+native-intent.tsx` sends it. `deepLinkKind()` returns null for the app's root URL, which Expo Router also passes on a cold start without a link, so that start sends nothing.

## Development sign in

- **Local stack.** Run `python manage.py setup_tasks_oauth` in the main checkout.
  It creates the dev app `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ` with `posthog://callback` among its redirect URIs.
  That covers `pnpm ios` and other local builds without `APP_VARIANT`. For an EAS development or preview build, add its URI as described in [Redirect URIs](#redirect-uris).
  In the app tap "Use a self-hosted instance", enter `http://localhost:8010`, keep the default client id.
  The dev app is not first-party, so the consent screen shows and access tokens last 1 hour, which exercises refresh often.
  - iOS simulator: `localhost` reaches the Mac.
  - Android emulator: run `adb reverse tcp:8010 tcp:8010` first, so `localhost` on the emulator reaches the Mac.
- **Personal API key** (dev builds only, `__DEV__`). Tap "Use a personal API key", pick the region or a custom host, paste a key with `user:read`, `organization:read`, `project:read` and the scopes of the screens you test (`task:read`, `task:write`, `user:write`, `conversation:write`, `today:read`, `query:read`, and for Views `dashboard:read`, `insight:read`, `file_system_shortcut:write`).
  The key never refreshes; a 401 ends the session.
- **Demo** (every build). "Try the demo" needs no account. "Exit demo" in Settings returns to the sign-in screen.

## Register a new OAuth app

For a self-hosted instance or a new environment, create the app in Django admin (`/admin/posthog/oauthapplication/add/`):

| Field | Value |
| --- | --- |
| Name | PostHog mobile |
| Client type | Public |
| Authorization grant type | Authorization code |
| Redirect URIs | `posthog://callback`, plus `posthog-dev://callback` and `posthog-preview://callback` for internal builds |
| Algorithm | RS256 |
| Is first party | On only for apps PostHog ships. It skips the consent screen and gives 7 day access tokens. |
| Scopes | Leave empty or `@default`, or list every scope above as the ceiling |

Copy the generated client id into the Client ID field that "Use a self-hosted instance" shows on the sign-in screen.

## Manual test

A real OAuth sign in cannot run in CI. Before a release, on a development build:

1. Sign in on US with a PostHog account. Check that the system browser opens, returns to the app and lands on the inbox.
2. Settings shows the host, your email and every project grouped by organization. Switch project, in Settings and from the project name at the top of the inbox menu, and check the inbox reloads.
3. Kill and reopen the app. It opens on the inbox without signing in again.
4. Cancel the browser during sign in. The sign-in screen says it was canceled and offers Try again.
5. Turn on airplane mode and reopen the app. The app stays signed in and shows load errors with Try again.
6. Against a local stack, delete the session's refresh and access token rows in Django admin (OAuth refresh tokens, OAuth access tokens), then pull to refresh. The app returns to sign in and says the session ended. First-party apps do not appear under Connected apps, so this needs admin.
7. Sign out from Settings. Confirm, then check that sign in comes back and a second launch stays signed out.
8. Repeat 1 on EU, and once against a local stack (see above).
