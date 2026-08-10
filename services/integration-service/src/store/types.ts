// The storage seam.
//
// Everything lives in ONE AWS secret, the way every other PostHog service does it:
// `integration-service-secrets`, holding flat `KEY: value` pairs. External Secrets Operator
// syncs it into a Kubernetes Secret and the service reads the mount — see fileStore.ts.
//
// OpenBao is the eventual destination (already deployed in dev via PostHog/charts) but is
// not in prod yet, so it becomes a second implementation of this interface, not a rewrite.

import type { SecretsSnapshot } from '../types.js'

export interface SecretStore {
    /**
     * Load every credential the manifest defines. Returns null when the mount is absent or
     * empty — a configuration gap, not an error.
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
 * This is PostHog's existing convention for rotatable keys (`SECRET_KEY_FALLBACKS`,
 * `JWT_SIGNING_KEY_FALLBACKS`), and the rotation guard in PostHog/secrets already grades
 * a key whose `_FALLBACKS` sibling is present, so the UI warns about an unsafe in-place
 * edit for free.
 *
 * It replaces what AWS staging labels used to do here, and has to. `AWSPREVIOUS` applies to
 * a whole secret version, so with every credential in one secret, rotating Google — or
 * simply adding an unrelated key — would consume the slot Stripe's in-flight rotation was
 * using and end its overlap silently. A mount cannot see staging labels at all, which
 * settles it.
 */
export const FALLBACK_SUFFIX = '_FALLBACKS'
