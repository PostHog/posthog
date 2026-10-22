# Security

Access rules that the security hub owns.
This product pulls them, decides them in-process, and answers the hub's questions.

## How it works

- A Temporal schedule (`security-sync-access-rules`, general-purpose queue) pulls this region's snapshot every 5 minutes.
  The hub also asks for a pull right after every change (`/api/security/sync-now/`).
- The snapshot lives in Redis with no TTL. Each process keeps an indexed copy and checks the Redis version at most every 30 seconds.
  When the hub is down, the last snapshot stays in force. When nothing is loaded, nobody is blocked and the login email code stays required.
- `facade.api.decide(subject, surface)` returns allow, block or exempt with the deciding rule.
  A posthog.com account is never blocked.
  A rule's scope picks the surfaces it decides. `all_access` covers `signup`, `app` and `ai_gateway`.
- The `security-access-enforcement` flag in PostHog's own project turns refusals on per surface.
  Its JSON payload maps each surface to a value, for example `{"signup": true, "app": false, "ai_gateway": false}`.
  A surface refuses requests only when its value is a literal `true`.
  Any other value, a missing payload or an unreadable flag leaves that surface logging only.
  Turning the flag off stops every refusal at once.
- Signup, login, sessions and the AI gateway call `facade.api.access_refused`.
  On an enforced surface, a block refuses the request, logs `security_access_refused` and counts `posthog_security_access_refusals_total`.
  Signup and app callers answer with the error code `access_blocked`.
  AI gateway callers answer in their own shape: OAuth authorization returns `access_denied`, the desktop token endpoint returns `reason: "blocked"`, and the wizard endpoints return a 403 with the AI gateway block message.
  On any other surface, a block logs `security_access_would_block`, counts `posthog_security_access_would_block_total` and refuses nobody.
  On the app surface, staff who impersonate a blocked account get through, and the match counts as a would-block.
  `posthog_security_access_decisions_total` counts every decision, so an empty would-block series still shows that the checks ran.
- Exemptions do not depend on the flag.
  `is_email_code_exempt` lets an account skip the emailed login code.
  `is_signup_risk_exempt` lets a signup skip the WorkOS Radar verdict.
- Every check fails open.
  A decision that raises refuses nobody, keeps the email code and the Radar verdict, and counts `posthog_security_access_decision_errors_total`.
- The AI gateway credential sweep (`posthog/tasks/wizard_blocklist.py`) revokes credentials for a block rule only while `ai_gateway` is enforced.
- To drop the emailed login code for every account during an email outage, add an `everyone` rule with scope `email_code` at the hub.
  Give it an expiry. The Redis switch it replaces capped itself at 7 days; a rule without `expiresAt` stays in force until somebody revokes it.
  It applies on the next pull plus the memo window, so allow about 6 minutes.

## Hub endpoints

`/api/security/{resolve,count-accounts,org-member-count,posthog-membership,sync-now}/`.
They are public because the hub runs outside the cluster.
A scoped HS256 token (`posthog:security_hub:internal`) pinned to this region and one operation is the only gate.
All five routes share one limit of 100 requests per minute.

## Settings

| Setting                             | Purpose                                                                               |
| ----------------------------------- | ------------------------------------------------------------------------------------- |
| `SECURITY_HUB_URL`                  | the hub's base URL; unset → no sync                                                   |
| `SECURITY_HUB_REGION`               | this region's id at the hub (`us`, `eu`)                                              |
| `SECURITY_HUB_INBOUND_JWT_SECRETS`  | verifies the hub's tokens; same value as the hub's `REGION_<ID>_OUTBOUND_JWT_SECRETS` |
| `SECURITY_HUB_OUTBOUND_JWT_SECRETS` | signs snapshot requests; same value as the hub's `REGION_<ID>_INBOUND_JWT_SECRETS`    |

Every value is unique per environment and region. Both secrets are comma-separated, newest first.

## Matching contract

`backend/tests/fixtures/access-rules.json` copies the hub's `test-vectors/access-rules.json`.
Change the hub's copy first, then copy it here, and keep both test suites passing.

## Alerts

Alert when `time() - posthog_security_access_rules_last_sync_timestamp_seconds` exceeds 30 minutes, and when `posthog_security_access_decision_errors_total` rises.
Every process that calls `current_snapshot()` — web, Celery and the worker — refreshes both gauges from the shared Redis state at most every 30 seconds, not only the worker that runs the sync. This keeps the alert accurate on any pod, including one that has never run a sync itself.
