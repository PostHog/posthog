// The storage seam.
//
// Everything lives in one AWS secret, `integration-service-secrets`, holding flat
// `KEY: value` pairs. External Secrets Operator syncs it into a Kubernetes Secret and the
// service reads the mount (fileStore.ts). OpenBao is the eventual destination, and becomes a
// second implementation of this interface rather than a rewrite.

import type { SecretsSnapshot } from '../types'

export interface SecretStore {
    /**
     * Load every credential the manifest defines. Returns null when the mount is absent or
     * empty, which is a configuration gap rather than an error.
     */
    load(): Promise<SecretsSnapshot | null>
}

/**
 * Reserved key naming the credentials that are in recovery, comma-separated.
 *
 * Uppercase and flat because PostHog/secrets only manages `[A-Z0-9_]+` keys with plain
 * string values. Never a credential itself: the provider manifest defines those, and this
 * name is not in it.
 */
export const RECOVERY_KEYS = 'INTEGRATION_RECOVERY_KEYS'

/**
 * Suffix marking the outgoing value during a rotation: `STRIPE_APP_SECRET_KEY` alongside
 * `STRIPE_APP_SECRET_KEY_FALLBACKS`, comma-separated, newest first.
 *
 * This follows PostHog's convention for rotatable keys (`SECRET_KEY_FALLBACKS`,
 * `JWT_SIGNING_KEY_FALLBACKS`), which the rotation guard in PostHog/secrets already grades.
 *
 * A sibling key rather than an AWS staging label, because `AWSPREVIOUS` applies to a whole
 * secret version: with every credential in one secret, rotating Google or simply adding an
 * unrelated key would consume the slot Stripe's in-flight rotation was using and end its
 * overlap silently. A mount cannot see staging labels at all.
 */
export const FALLBACK_SUFFIX = '_FALLBACKS'
