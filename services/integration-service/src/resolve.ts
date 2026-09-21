// Turns a verified token plus what the mount holds into a response.
//
// The `keys` claim alone bounds what a request may read. There is no per-deployment
// allowlist, because a list bounds nothing the deployment's signing key does not already
// bound: a compromised deployment is contained by revoking that key.
//
// `missing` covers both a name the mount does not carry and a reserved entry it refuses to
// serve, reported per key rather than failing the batch.

import { logger } from './lib/logging'
import { observeResolve, previousVersionServedTotal } from './metrics'
import type { CallerIdentity, MountedSecrets, ResolveOutcome } from './types'

/** Stand-in label for a name the mount does not carry, which is caller-supplied text. */
const UNKNOWN_KEY = 'unknown'

/** Wire shape of one resolved secret. snake_case because Python is the primary consumer. */
export interface WireSecret {
    state: string
    value?: string
    /**
     * The staged value, still named `previous` on the wire. The name is wrong — it is the
     * incoming value, not the outgoing one — but renaming a field both sides read needs a
     * release where each accepts either, so the internal model is accurate and this boundary
     * lags deliberately.
     */
    previous?: string
    version_id: string
    fetched_at: string
}

export interface ResolveResponse {
    secrets: Record<string, WireSecret>
    missing: string[]
}

export function resolveKeys(identity: CallerIdentity, mounted: MountedSecrets): ResolveResponse {
    const secrets: Record<string, WireSecret> = {}
    const missing: string[] = []
    const served: string[] = []

    for (const key of identity.requestedKeys) {
        const secret = mounted.secrets[key]
        if (!secret) {
            missing.push(key)
            observeResolve(identity.deployment, UNKNOWN_KEY, 'missing')
            continue
        }

        const outcome: ResolveOutcome = secret.state === 'recovery' ? 'recovery' : 'ok'
        const wire: WireSecret = {
            state: secret.state,
            version_id: secret.versionId,
            fetched_at: secret.fetchedAt,
        }
        if (secret.value !== undefined) {
            wire.value = secret.value
        }
        if (secret.incoming !== undefined) {
            wire.previous = secret.incoming
            previousVersionServedTotal.labels({ key }).inc()
        }
        secrets[key] = wire
        observeResolve(identity.deployment, key, outcome)
        if (outcome === 'ok') {
            served.push(key)
        }
    }

    // One audit line per request rather than per key, so Loki keeps the whole request
    // together. The key list is bounded by the token scope, so it stays readable.
    logger.info('secrets:resolved', { deployment: identity.deployment, caller: identity.caller, served, missing })

    return { secrets, missing }
}
