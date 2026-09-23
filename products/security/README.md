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
- Phase 1 enforces only `email_code` exemptions. Signup, login, sessions and the AI gateway call `shadow_check`, which logs `security_access_would_block` and counts `posthog_security_access_would_block_total`, and blocks nobody.

## Hub endpoints

`/api/security/{resolve,count-accounts,org-member-count,posthog-membership,sync-now,mfa-bypass-export}/`.
They are public because the hub runs outside the cluster.
A scoped HS256 token (`posthog:security_hub:internal`) pinned to this region and one operation is the only gate.
All six routes share one limit of 100 requests per minute.

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
