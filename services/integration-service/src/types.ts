// Shared types for the integration-service.

/**
 * How a credential field currently stands relative to a rotation.
 *
 * - `steady`   — one live value. No AWSPREVIOUS version, or it holds the same value.
 * - `rotating` — a `<KEY>_FALLBACKS` sibling holds a different value. Both are served;
 *                callers that can dual-accept try current first, then previous. This is
 *                the window in which a third party may still be handing back tokens
 *                minted against the old value.
 * - `recovery` — the value is known-burned and no valid replacement exists yet. No
 *                value is served at all; callers raise a typed error so the product
 *                surfaces "reconnect needed" instead of hammering a third party with
 *                a credential that cannot work.
 */
export type SecretState = 'steady' | 'rotating' | 'recovery'

/** One credential field as the store resolved it. */
export interface ResolvedSecret {
    state: SecretState
    /** Absent only in `recovery`. */
    value?: string
    /** Present only in `rotating`. */
    previous?: string
    /** AWS version id the value came from. */
    versionId: string
    /** When the secret was last read from Secrets Manager. */
    fetchedAt: string
}

/** Every credential field, as loaded from the one integration-service secret. */
export interface SecretsSnapshot {
    fetchedAt: string
    versionId: string
    /**
     * When the secret last changed. Used as the "have callers picked up the new value"
     * threshold — see safeToRetirePrevious. Not per-field: an unrelated edit moves it
     * forward, which only delays a retirement verdict.
     */
    versionCreatedAt: string | null
    secrets: Record<string, ResolvedSecret>
}

/** What a verified request is allowed to do, and who to attribute it to. */
export interface CallerIdentity {
    /**
     * The pod set that signed the token, established by which key verified it. This is
     * the authenticated identity and the authorization boundary.
     */
    deployment: string
    /**
     * The product code path that wanted the credential. Caller-supplied and NOT verified
     * — it is for metrics and audit, and grants nothing. Always one of the recognised
     * names or a constant, so it is safe as a metric label.
     */
    product: string
    /** The exact keys this one request asked for, from the token's `keys` claim. */
    requestedKeys: readonly string[]
}

/** Per-key outcome, used for both metrics and the usage rollup. */
export type ResolveOutcome = 'ok' | 'missing' | 'recovery'
