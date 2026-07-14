# Push subscription identity verification

Securing the binding of a mobile push device token to a `distinct_id`, so an attacker who only holds
the (public, app-embedded) project token cannot point another user's notifications at their own device.

## Why this is needed

A push device token (FCM registration token / APNs device token) is a delivery **address**, not a
credential — FCM/APNs issue one to any app instance, and an attacker owns their own token legitimately.
Possession proves "deliver here", never "this device belongs to user X". Today `POST /api/push_subscriptions`
authenticates with the **public project token**, which identifies the project but not the person, so any
holder of it can register a device under an arbitrary `distinct_id` (notification takeover / "rebind").

This mirrors what leading platforms do: the fix must require a server-attested proof that the caller may
act for that `distinct_id`. Braze's "SDK Authentication" is the reference design — the customer's backend
mints a short-lived signed JWT whose subject is the user id, and the platform verifies it. (Customer.io and
Brevo/WonderPush "trust the client" and do **not** defend against this — the state we're leaving behind.)

## The token

A short-lived **JWT (HS256)** signed with the project's **secret API key** (`Team.secret_api_token`).
Minted by the **customer's backend** (the only party that authenticated the end user), never in the app.

| Claim    | Value                                                    |
| -------- | -------------------------------------------------------- |
| `sub`    | the `distinct_id` being registered                       |
| `app_id` | the FCM `project_id` / APNs `bundle_id` the token is for |
| `aud`    | `posthog:push_identity`                                  |
| `exp`    | short expiry (SDK refreshes on failure)                  |

Verification accepts the current **or** backup secret, so a key rotation doesn't reject in-flight tokens.
`sub` and `app_id` are both bound, so a token minted for one identity/app can't authorize another.

Reference signer + verifier: `push_identity_tokens.py` (`sign_push_identity_token` shows exactly what the
customer backend produces; PostHog's ingestion only ever calls `verify_push_identity_token`).

## Flow

1. Customer backend authenticates the user, then mints the token for `(distinct_id, app_id)` with the
   project secret key.
2. The app receives the token and calls `POST /api/push_subscriptions` with the usual fields plus
   `identity_token`.
3. The endpoint verifies the signature, `exp`, and that `sub`/`app_id` match the registration.

## Rollout — per integration, three stages

Set `push_identity_verification` in the Firebase/APNs integration's `config` (mirrors Braze's staged
rollout so it can be turned on without breaking existing traffic):

- **`disabled`** (default) — `identity_token` ignored; current behavior.
- **`optional`** — token is verified and the outcome recorded (`push_subscription_identity_verification`
  metric, labelled by `mode`/`outcome`), but registration still succeeds. Use this to confirm the backend
  is minting valid tokens before enforcing.
- **`required`** — a registration without a valid token is rejected (`401`).

## Not covered here (follow-ups)

- SDK support for attaching `identity_token` and refreshing it on a verification-failure callback.
- A Channels UI control for the per-integration mode (today it's a `config` value).
- Clearing the binding on logout (an SDK/endpoint concern, analogous to Customer.io `clearIdentify`).
