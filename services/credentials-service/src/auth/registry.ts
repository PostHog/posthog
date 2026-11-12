// The platform-secrets callers: one flat `__CALLER_KEY_<DEPLOYMENT>` HS256 entry per caller in
// the same mounted secret as the secrets. The same value goes into that deployment's own
// secret as CREDENTIALS_SERVICE_JWT_SECRET. These keys verify `/v1/secrets/resolve` tokens and
// nothing else: integration callers have their own Ed25519 registry (integration-keys.ts).
//
// An optional `__ALLOWED_SECRETS_<DEPLOYMENT>` entry, comma-separated, limits the names that
// deployment may resolve. It sits in the same secret, so one edit changes a key and its
// allowlist together.
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

/** Reserved-prefixed, so the mount never serves an allowlist as a secret. */
export const ALLOWED_SECRETS_PREFIX = `${RESERVED_PREFIX}ALLOWED_SECRETS_`

/** The names each deployment may resolve. A deployment with no entry is not restricted. */
export type SecretAllowlists = Record<string, ReadonlySet<string>>

function deploymentFromEntry(entry: string, prefix: string): string {
    return entry.slice(prefix.length).toLowerCase().replaceAll('_', '-')
}

function hasOwn(record: object, key: string): boolean {
    return Object.prototype.hasOwnProperty.call(record, key)
}

function commaList(value: string): string[] {
    return value
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
}

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
    return parseSigningKeys((await readMount(dir)) ?? {})
}

/** Every signing key in one snapshot of the secret, keyed by deployment. */
export function parseSigningKeys(values: Record<string, string>): SigningKeys {
    const keys: SigningKeys = {}
    for (const [entry, value] of Object.entries(values)) {
        if (!entry.startsWith(CALLER_KEY_PREFIX)) {
            continue
        }
        const listed = commaList(value)
        if (listed.length === 0) {
            continue
        }
        const deployment = deploymentFromEntry(entry, CALLER_KEY_PREFIX)
        if (keys[deployment]) {
            // Silently keeping the last entry would drop a key set a revocation had just
            // edited, so the revocation would look like it landed and would not have.
            throw new Error(`two mount entries both name the deployment ${deployment}`)
        }
        keys[deployment] = listed
    }
    return keys
}

/**
 * Every `__ALLOWED_SECRETS_<DEPLOYMENT>` entry, keyed by deployment. An empty entry allows
 * nothing. Throws when an entry names a reserved name, because the route never serves one and
 * the edit is a mistake. Throws when the deployment has no signing key, because a typo in the
 * entry name would leave the real deployment with no limit.
 */
export function parseSecretAllowlists(values: Record<string, string>, keys: SigningKeys): SecretAllowlists {
    const allowlists: SecretAllowlists = {}
    for (const [entry, value] of Object.entries(values)) {
        if (!entry.startsWith(ALLOWED_SECRETS_PREFIX)) {
            continue
        }
        const deployment = deploymentFromEntry(entry, ALLOWED_SECRETS_PREFIX)
        if (hasOwn(allowlists, deployment)) {
            throw new Error(`two allowlist entries both name the deployment ${deployment}`)
        }
        if (!hasOwn(keys, deployment)) {
            throw new Error(`the allowlist for ${deployment} names no deployment with a signing key`)
        }
        const names = commaList(value)
        const reserved = names.find((name) => name.startsWith(RESERVED_PREFIX))
        if (reserved !== undefined) {
            throw new Error(`the allowlist for ${deployment} names the reserved entry ${reserved}`)
        }
        allowlists[deployment] = new Set(names)
    }
    return allowlists
}

export class SigningKeyLoader {
    private keys: SigningKeys = {}
    private allowlists: SecretAllowlists = {}
    private loaded = false

    /**
     * @param dir The mount directory `load()` and `reload()` read. A server fed by a secret
     *   source calls `loadFrom()` and `reloadFrom()` instead and passes a description of the
     *   source here, for error messages only.
     */
    constructor(private readonly dir: string) {}

    /** Replace the in-memory key set. Throws on the first load so boot fails closed. */
    async load(): Promise<void> {
        this.loadFrom((await readMount(this.dir)) ?? {})
    }

    /** As `load()`, from one snapshot of the secret. */
    loadFrom(values: Record<string, string>): void {
        const keys = parseSigningKeys(values)
        if (Object.keys(keys).length === 0) {
            throw new Error(`no ${CALLER_KEY_PREFIX}* entries in ${this.dir}`)
        }
        assertNoSharedKeys(keys)
        const allowlists = parseSecretAllowlists(values, keys)
        this.keys = keys
        this.allowlists = allowlists
        this.loaded = true
        signingKeysLastLoadedTimestamp.set(Date.now() / 1000)
        logger.info('auth:signing_keys_loaded', {
            deployments: Object.keys(keys).sort(),
            allowlisted: Object.keys(allowlists).sort(),
        })
    }

    /**
     * Reload, keeping the previous keys if the mount is unreadable or invalid, so a
     * malformed edit cannot lock a running fleet out. The metrics make that fail-open
     * visible when a revocation does not land.
     */
    async reload(): Promise<void> {
        this.reloadFrom(await readMount(this.dir))
    }

    /** As `reload()`, from one snapshot of the secret. Null means the source could not be read. */
    reloadFrom(values: Record<string, string> | null): void {
        try {
            if (values === null) {
                throw new Error(`could not read ${this.dir}`)
            }
            this.loadFrom(values)
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

    /** The names `deployment` may resolve, or null when it has no allowlist. */
    allowedSecrets(deployment: string): ReadonlySet<string> | null {
        return hasOwn(this.allowlists, deployment) ? (this.allowlists[deployment] ?? null) : null
    }
}
