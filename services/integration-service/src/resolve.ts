// Turns a verified token plus what the mount currently holds into a response.
//
// What a request may read is bounded by the `keys` claim alone: the token IS the request,
// so a leaked one unlocks the fields of one call rather than everything. There is no
// per-deployment allowlist, because a list bounds nothing the per-deployment signing key
// does not already bound — a compromised deployment is contained by revoking its key.
//
// `missing` covers a name the mount does not carry and a reserved entry the mount refuses
// to serve. Both are reported per key rather than failing the batch.

import { logger } from './lib/logging'
import { observeResolve, previousVersionServedTotal } from './metrics'
import type { CallerIdentity, MountedCredentials, ResolveOutcome } from './types'
import type { UsageRecorder } from './usage/recorder'

/** Stand-in label for a name the mount does not carry, which is caller-supplied text. */
const UNKNOWN_KEY = 'unknown'

/** Wire shape of one resolved credential. snake_case because Python is the primary consumer. */
export interface WireSecret {
    state: string
    value?: string
    previous?: string
    version_id: string
    fetched_at: string
}

export interface ResolveResponse {
    secrets: Record<string, WireSecret>
    missing: string[]
}

export function resolveKeys(
    identity: CallerIdentity,
    mounted: MountedCredentials,
    recorder: UsageRecorder
): ResolveResponse {
    const secrets: Record<string, WireSecret> = {}
    const missing: string[] = []
    const served: string[] = []

    for (const key of identity.requestedKeys) {
        const credential = mounted.credentials[key]
        if (!credential) {
            missing.push(key)
            observeResolve(identity.deployment, UNKNOWN_KEY, 'missing')
            continue
        }

        const outcome: ResolveOutcome = credential.state === 'recovery' ? 'recovery' : 'ok'
        const wire: WireSecret = {
            state: credential.state,
            version_id: credential.versionId,
            fetched_at: credential.fetchedAt,
        }
        if (credential.value !== undefined) {
            wire.value = credential.value
        }
        if (credential.previous !== undefined) {
            wire.previous = credential.previous
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

    recorder.record(identity.deployment, served)

    return { secrets, missing }
}
