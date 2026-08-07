// The service's own signing keys, one entry per calling deployment.
//
// Stored in this service's AWS secret as flat uppercase keys, which is what the
// PostHog/secrets CLI and UI can manage:
//
//   integration-service-secrets
//     CALLER_KEY_POSTHOG_DJANGO                  = "<new>,<old>"
//     CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE  = "<new>,<old>"
//
// The same value is also set as INTEGRATION_SERVICE_JWT_SECRET in that deployment's own
// secret. Duplicating one value per deployment is inherent to shared-secret auth, and it
// replaces 26 duplicated credentials with one.
//
// Deployment names are DERIVED from the entries present, not declared in code. Onboarding
// a caller or revoking a compromised one is therefore a secrets edit with no deploy — and
// revoking one deployment's key leaves every other deployment working, which is the
// containment this design relies on.
//
// Held in process memory only, never written to Redis. Everything else this service
// caches is a credential sealed under KMS; these are the keys that authenticate callers.

import { GetSecretValueCommand, type SecretsManagerClient } from '@aws-sdk/client-secrets-manager'

import { logger } from '../lib/logging.js'
import type { SigningKeys } from './types.js'

const KEY_PREFIX = 'CALLER_KEY_'

/** `temporal-worker-data-warehouse` -> `CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE`. */
export function secretKeyFor(deployment: string): string {
    return `${KEY_PREFIX}${deployment.toUpperCase().replaceAll('-', '_')}`
}

/** `CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE` -> `temporal-worker-data-warehouse`. */
function deploymentFor(secretKey: string): string {
    return secretKey.slice(KEY_PREFIX.length).toLowerCase().replaceAll('_', '-')
}

function parseSigningKeys(raw: string): SigningKeys {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('signing key secret is not a JSON object')
    }
    const flat = parsed as Record<string, unknown>

    const keys: SigningKeys = {}
    for (const [secretKey, value] of Object.entries(flat)) {
        if (!secretKey.startsWith(KEY_PREFIX) || typeof value !== 'string') {
            continue
        }
        // Comma-separated `new,old`, whitespace-trimmed. Same convention as
        // RECORDING_API_JWT_SECRET and the minting side.
        const parts = value
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean)
        if (parts.length > 0) {
            keys[deploymentFor(secretKey)] = parts
        }
    }
    return keys
}

export class SigningKeyLoader {
    private keys: SigningKeys = {}
    private loaded = false

    constructor(
        private readonly client: SecretsManagerClient,
        private readonly secretId: string
    ) {}

    /** Replace the in-memory key set. Throws on the first load so boot fails closed. */
    async load(): Promise<void> {
        const response = await this.client.send(new GetSecretValueCommand({ SecretId: this.secretId }))
        if (!response.SecretString) {
            throw new Error(`signing key secret ${this.secretId} has no value`)
        }
        const keys = parseSigningKeys(response.SecretString)
        if (Object.keys(keys).length === 0) {
            throw new Error(`signing key secret ${this.secretId} defines no deployment keys`)
        }
        this.keys = keys
        this.loaded = true
        logger.info('auth:signing_keys_loaded', { deployments: Object.keys(keys).sort() })
    }

    /**
     * Reload, keeping the previous keys if the new value is unreadable. A malformed edit
     * must not lock every caller out of a running fleet; it should page instead.
     */
    async reload(): Promise<void> {
        try {
            await this.load()
        } catch (err) {
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
