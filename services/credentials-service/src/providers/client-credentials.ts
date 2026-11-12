// PostHog's own OAuth client for a provider, read from the platform-secret snapshot in process.
// A port of `client_credentials_for_kind` and `fallback_client_credentials_for_kind`.

import type { Secret } from '../types'
import type { ClientSecretKeys } from './schema'

export interface ClientCredentials {
    clientId: string
    clientSecret: string
    /** `fallback` marks a grant that only a rotated app can refresh (`oauth_uses_legacy_client`). */
    source: 'primary' | 'fallback'
}

/** The app is not set up on this deployment. Not the row's fault, so a refresh must not count it as a failure. */
export class ProviderNotConfiguredError extends Error {
    constructor(readonly kind: string) {
        super(`the ${kind} app is not configured`)
        this.name = 'ProviderNotConfiguredError'
    }
}

/**
 * The client credentials to try, in order: the primary pair, then each configured fallback.
 *
 * Only the live value of each secret is used, as `get_many_or_settings` does. A secret in
 * `recovery` has no value, so it counts as unset.
 */
export function clientCredentialCandidates(
    kind: string,
    keys: ClientSecretKeys,
    secrets: Readonly<Record<string, Secret>>
): ClientCredentials[] {
    const value = (name: string | undefined): string | undefined =>
        name ? secrets[name]?.value || undefined : undefined

    const clientId = value(keys.clientId)
    const clientSecret = value(keys.clientSecret)
    // Both halves, even where only the id is sent: an unusable app then fails before the user consents.
    if (!clientId || !clientSecret) {
        throw new ProviderNotConfiguredError(kind)
    }
    const candidates: ClientCredentials[] = [{ clientId, clientSecret, source: 'primary' }]
    for (const fallback of keys.fallbacks ?? []) {
        const fallbackSecret = value(fallback.clientSecret)
        if (fallbackSecret) {
            candidates.push({
                clientId: value(fallback.clientId) ?? clientId,
                clientSecret: fallbackSecret,
                source: 'fallback',
            })
        }
    }
    return candidates
}
