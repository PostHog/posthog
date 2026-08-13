// The service's signing keys, one flat `__CALLER_KEY_<DEPLOYMENT>` entry per caller in the
// same mounted secret as the secrets. The same value goes into that deployment's own
// secret as INTEGRATION_SERVICE_JWT_SECRET.
//
// Deployment names are DERIVED from the entries present, not declared in code, so revoking
// a compromised caller is a secrets edit with no deploy, and it leaves every other caller
// working. That containment is what this design relies on instead of an allowlist.

import { logger } from '../lib/logging'
import { signingKeyReloadFailuresTotal, signingKeysLastLoadedTimestamp } from '../metrics'
import { RESERVED_PREFIX, readMount } from '../mount'
import type { SigningKeys } from './types'

/** Reserved-prefixed, so the mount never serves a signing key as a secret. */
export const CALLER_KEY_PREFIX = `${RESERVED_PREFIX}CALLER_KEY_`

/**
 * Reject a value listed under two deployments: the verifier stops at the first entry that
 * verifies, so they collapse into one identity, revoking either fails to cut it off, and
 * every attribution names the wrong caller. Invisible in an opaque value, so fail at load.
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

/** Every signing key on the mount, keyed by deployment. */
export async function readSigningKeys(dir: string): Promise<SigningKeys> {
    const values = (await readMount(dir)) ?? {}
    const keys: SigningKeys = {}
    for (const [entry, value] of Object.entries(values)) {
        if (!entry.startsWith(CALLER_KEY_PREFIX)) {
            continue
        }
        const listed = value
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean)
        if (listed.length === 0) {
            continue
        }
        const deployment = entry.slice(CALLER_KEY_PREFIX.length).toLowerCase().replaceAll('_', '-')
        if (keys[deployment]) {
            // Silently keeping the last entry would drop a key set a revocation had just
            // edited, so the revocation would look like it landed and would not have.
            throw new Error(`two mount entries both name the deployment ${deployment}`)
        }
        keys[deployment] = listed
    }
    return keys
}

export class SigningKeyLoader {
    private keys: SigningKeys = {}
    private loaded = false

    constructor(private readonly dir: string) {}

    /** Replace the in-memory key set. Throws on the first load so boot fails closed. */
    async load(): Promise<void> {
        const keys = await readSigningKeys(this.dir)
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
     * Reload, keeping the previous keys if the mount is unreadable or invalid, so a
     * malformed edit cannot lock a running fleet out. The metrics make that fail-open
     * visible when a revocation does not land.
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
