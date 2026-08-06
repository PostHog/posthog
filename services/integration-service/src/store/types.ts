// The storage seam.
//
// Phase 1 stores credentials in AWS Secrets Manager. OpenBao is the eventual
// destination (it is already deployed in dev via PostHog/charts) but is not in prod
// yet, so it becomes a second implementation of this interface rather than a rewrite.
// Keep everything AWS-shaped behind here.

import type { ProviderSnapshot } from '../types.js'

export interface SecretStore {
    /**
     * Load one provider's credential fields, including whatever the previous version
     * held so a rotation in flight can be served.
     *
     * Returns null when the provider has no secret in this environment — a
     * configuration gap, not an error, since a region may legitimately not hold
     * credentials for every provider.
     */
    loadProvider(provider: string): Promise<ProviderSnapshot | null>
}

/** Reserved key inside a provider's JSON blob; never a credential field. */
export const STATE_MARKER_KEY = '_state'
