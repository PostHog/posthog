// Turns a verified token plus what the mount holds into a response.
//
// The `keys` claim bounds what a request may read. A deployment with an
// `__ALLOWED_SECRETS_<DEPLOYMENT>` entry is also bounded by that list. A deployment with no
// entry may read any name that is not reserved.
//
// A reserved name (`__` prefix, for example the `__PROVIDER_` OAuth client secrets and minter
// keys) is never served to anyone. The mount already drops those entries, and this file
// refuses them again so a change to the mount cannot expose one.
//
// `missing` covers a name the mount does not carry, a reserved name and a name outside the
// allowlist, reported per key rather than failing the batch. The response does not say which,
// so a caller cannot use it to learn what the mount holds.

import { logger } from './lib/logging'
import { observeResolve, previousVersionServedTotal } from './metrics'
import { RESERVED_PREFIX } from './mount'
import type { CallerIdentity, MountedSecrets, ResolveOutcome } from './types'

/** Stand-in label for a name the mount does not carry, which is caller-supplied text. */
const UNKNOWN_KEY = 'unknown'

/** Wire shape of one resolved secret. snake_case because Python is the primary consumer. */
export interface WireSecret {
    state: string
    value?: string
    /** The staged value that a rotation has accepted but not yet made live. */
    incoming?: string
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
    const refused: string[] = []

    for (const key of identity.requestedKeys) {
        if (key.startsWith(RESERVED_PREFIX) || (identity.allowedKeys !== null && !identity.allowedKeys.has(key))) {
            missing.push(key)
            refused.push(key)
            observeResolve(identity.deployment, UNKNOWN_KEY, 'not_allowed')
            continue
        }
        const secret = Object.prototype.hasOwnProperty.call(mounted.secrets, key) ? mounted.secrets[key] : undefined
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
            wire.incoming = secret.incoming
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
    logger.info('secrets:resolved', {
        deployment: identity.deployment,
        caller: identity.caller,
        served,
        missing,
        refused,
    })

    return { secrets, missing }
}
