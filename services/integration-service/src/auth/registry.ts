// The service's signing keys, one per calling deployment.
//
// They sit in the same mounted secret as the credentials, as flat uppercase keys, which is
// what the PostHog/secrets CLI and UI can manage:
//
//   integration-service-secrets
//     STRIPE_APP_SECRET_KEY                      = "<credential>"
//     CALLER_KEY_POSTHOG_DJANGO                  = "<new>,<old>"
//     CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE  = "<new>,<old>"
//
// The same value goes into that deployment's own secret as INTEGRATION_SERVICE_JWT_SECRET.
// Duplicating one value per deployment is inherent to shared-secret auth, and it replaces
// 26 duplicated credentials with one.
//
// Deployment names are DERIVED from the entries present, not declared in code. Onboarding a
// caller or revoking a compromised one is therefore a secrets edit with no deploy — and
// revoking one deployment's key leaves every other deployment working, which is the
// containment this design relies on.
//
// Held in process memory only. These are the keys that authenticate callers.

import { logger } from '../lib/logging.js'
import { signingKeyReloadFailuresTotal, signingKeysLastLoadedTimestamp } from '../metrics.js'
import { readSigningKeys } from '../store/fileStore.js'
import type { SigningKeys } from './types.js'

export const CALLER_KEY_PREFIX = 'CALLER_KEY_'

/** `temporal-worker-data-warehouse` -> `CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE`. */
export function secretKeyFor(deployment: string): string {
    return `${CALLER_KEY_PREFIX}${deployment.toUpperCase().replaceAll('-', '_')}`
}

/**
 * Reject a key value listed under more than one deployment.
 *
 * Two deployments sharing a value would collapse into one identity: the verifier stops at
 * the first entry that verifies, so both resolve to whichever CALLER_KEY_* came first.
 * Revoking one would then not cut it off, because the same value is still listed under the
 * other name — and revocation is the containment this design relies on. Attribution goes
 * with it: the audit log, the usage rollup and safeToRetirePrevious would all name the
 * wrong caller. Fail at load instead; a paste error is the likely cause, and it is not
 * visible in an opaque value.
 */
export function assertNoSharedKeys(keys: SigningKeys): void {
    const owner = new Map<string, string>()
    for (const [deployment, values] of Object.entries(keys)) {
        for (const value of values) {
            const existing = owner.get(value)
            if (existing && existing !== deployment) {
                throw new Error(`signing key for ${deployment} is also listed for ${existing}`)
            }
            owner.set(value, deployment)
        }
    }
}

export class SigningKeyLoader {
    private keys: SigningKeys = {}
    private loaded = false

    constructor(private readonly dir: string) {}

    /** Replace the in-memory key set. Throws on the first load so boot fails closed. */
    async load(): Promise<void> {
        const keys = await readSigningKeys(this.dir, CALLER_KEY_PREFIX)
        if (Object.keys(keys).length === 0) {
            throw new Error(`no ${CALLER_KEY_PREFIX}* entries on the secret mount at ${this.dir}`)
        }
        assertNoSharedKeys(keys)
        this.keys = keys
        this.loaded = true
        signingKeysLastLoadedTimestamp.set(Date.now() / 1000)
        logger.info('auth:signing_keys_loaded', { deployments: Object.keys(keys).sort() })
    }

    /**
     * Reload, keeping the previous keys if the mount is unreadable or invalid. A malformed
     * edit must not lock every caller out of a running fleet.
     *
     * That fail-open is what the two metrics exist for: staleness on the gauge means "a
     * revocation has not landed on this pod".
     */
    async reload(): Promise<void> {
        try {
            await this.load()
        } catch (err) {
            signingKeyReloadFailuresTotal.inc()
            logger.error('auth:signing_keys_reload_failed', {
                error: err instanceof Error ? err.message : String(err),
            })
        }
    }

    get isLoaded(): boolean {
        return this.loaded
    }

    /** Every deployment and its accepted keys, for the verifier to try in turn. */
    entries(): [string, string[]][] {
        return Object.entries(this.keys)
    }
}
