// Turns a verified token into a response.
//
// What a request may read is bounded by the `keys` claim alone: the token IS the request,
// so a leaked one unlocks the fields of one call rather than everything.
//
// There is deliberately no per-deployment provider allowlist. Every authenticated
// deployment may read any credential in the manifest, because a list bounds nothing the
// per-deployment signing key does not already bound: a compromised deployment is contained
// by revoking its key. What it actually read is in the audit log and the usage rollup.
//
// `missing` covers both an unknown key name and a manifest key with no value here. Both
// are reported per key rather than failing the batch.

import { logger } from '../lib/logging'
import { observeResolve, previousVersionServedTotal } from '../metrics'
import { providerForKey } from '../providers'
import type { CallerIdentity, ResolveOutcome, SecretsSnapshot } from '../types'
import type { UsageRecorder } from '../usage/recorder'

/** Stand-in label for anything a caller named that the provider manifest does not define. */
const UNKNOWN_LABEL = 'unknown'

/** Wire shape of one resolved field. snake_case because Python is the primary consumer. */
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

/**
 * Thrown when this pod holds no credential snapshot.
 *
 * Deliberately not answered as an all-`missing` response, because a caller treats a missing
 * key as terminal. Answering that way during a cold start would turn an unavailable service
 * into what looks like a deleted credential.
 */
export class SnapshotUnavailableError extends Error {
    constructor() {
        super('no credential snapshot is loaded')
        this.name = 'SnapshotUnavailableError'
    }
}

export interface ResolveDeps {
    loadSecrets: () => Promise<SecretsSnapshot | null>
    recorder: UsageRecorder
}

export async function resolveKeys(identity: CallerIdentity, deps: ResolveDeps): Promise<ResolveResponse> {
    const secrets: Record<string, WireSecret> = {}
    const missing: string[] = []
    const served: string[] = []

    const snapshot = await deps.loadSecrets()
    if (!snapshot) {
        throw new SnapshotUnavailableError()
    }

    for (const key of identity.requestedKeys) {
        const provider = providerForKey(key)
        if (!provider) {
            missing.push(key)
            // Constant labels, not the key itself: a key absent from the manifest is a
            // caller-supplied string, and labelling with it would let any holder of a
            // signing key grow this process's series set without bound. The real name still
            // reaches the response and the log line.
            observeResolve(identity, UNKNOWN_LABEL, UNKNOWN_LABEL, 'missing')
            continue
        }
        const resolved = snapshot.secrets[key]
        if (!resolved) {
            missing.push(key)
            observeResolve(identity, provider, key, 'missing')
            continue
        }

        const outcome: ResolveOutcome = resolved.state === 'recovery' ? 'recovery' : 'ok'
        const wire: WireSecret = {
            state: resolved.state,
            version_id: resolved.versionId,
            fetched_at: resolved.fetchedAt,
        }
        if (resolved.value !== undefined) {
            wire.value = resolved.value
        }
        if (resolved.previous !== undefined) {
            wire.previous = resolved.previous
            previousVersionServedTotal.labels({ provider, key }).inc()
        }
        secrets[key] = wire
        observeResolve(identity, provider, key, outcome)
        if (outcome === 'ok') {
            served.push(key)
        }
    }

    // One audit line per request rather than per key, so Loki keeps the whole request
    // together. The key list is bounded by the token scope, so it stays readable.
    logger.info('secrets:resolved', {
        deployment: identity.deployment,
        product: identity.product,
        served,
        missing,
    })

    deps.recorder.record(identity.deployment, served)

    return { secrets, missing }
}
