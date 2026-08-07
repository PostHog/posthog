// Turns a verified token into a response.
//
// Two independent gates, in this order:
//   1. the `keys` claim — what this request asked for (bounds a leaked token);
//   2. the deployment's provider allowlist — what this pod may ever have (bounds a
//      compromised deployment).
//
// A key outside the allowlist is reported in `denied` rather than failing the whole
// request, so a policy mistake shows up as one named field a human can act on instead of
// an opaque 403. Same for `missing`: an unknown key name and an unpopulated credential
// are both diagnosable states, not errors.

import { ALL_PROVIDERS } from '../deployments.js'
import { logger } from '../lib/logging.js'
import { observeResolve, previousVersionServedTotal } from '../metrics.js'
import { providerForKey } from '../providers.js'
import type { CallerIdentity, ProviderSnapshot, ResolveOutcome } from '../types.js'
import type { UsageRecorder } from '../usage/recorder.js'

/** Stand-in label for anything a caller named that the provider manifest does not define. */
const UNKNOWN_LABEL = 'unknown'

// Read the allowlist off the verified identity rather than the global table. The verifier
// is the one place that decides what a token is allowed, and everything downstream should
// answer to that decision rather than looking it up again.
function allows(identity: CallerIdentity, provider: string): boolean {
    return identity.allowedProviders === ALL_PROVIDERS || identity.allowedProviders.includes(provider)
}

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
    denied: string[]
    missing: string[]
}

export interface ResolveDeps {
    loadProvider: (provider: string) => Promise<ProviderSnapshot | null>
    recorder: UsageRecorder
}

export async function resolveKeys(identity: CallerIdentity, deps: ResolveDeps): Promise<ResolveResponse> {
    const secrets: Record<string, WireSecret> = {}
    const denied: string[] = []
    const missing: string[] = []
    const served: string[] = []

    // Group by provider so N fields of the same provider cost one snapshot load.
    const byProvider = new Map<string, string[]>()
    for (const key of identity.requestedKeys) {
        const provider = providerForKey(key)
        if (!provider) {
            missing.push(key)
            // Constant labels, not the key itself. A key absent from the manifest is a
            // caller-supplied string, and putting it on a metric would let any holder of
            // a signing key grow this process's series set without bound. The real name
            // still reaches the response and the log line, neither of which is a label.
            observeResolve(identity, UNKNOWN_LABEL, UNKNOWN_LABEL, 'missing')
            continue
        }
        if (!allows(identity, provider)) {
            denied.push(key)
            observeResolve(identity, provider, key, 'denied')
            continue
        }
        const bucket = byProvider.get(provider)
        if (bucket) {
            bucket.push(key)
        } else {
            byProvider.set(provider, [key])
        }
    }

    for (const [provider, keys] of byProvider) {
        const snapshot = await deps.loadProvider(provider)
        for (const key of keys) {
            const resolved = snapshot?.secrets[key]
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
    }

    // One audit line per request rather than per key: the key list is bounded by the
    // token scope, so it stays readable, and Loki keeps the whole request together.
    logger.info('secrets:resolved', {
        deployment: identity.deployment,
        product: identity.product,
        served,
        denied,
        missing,
    })

    deps.recorder.record(identity.deployment, served)

    return { secrets, denied, missing }
}
