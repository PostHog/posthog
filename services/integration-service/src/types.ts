// Shared types for the integration-service.

/**
 * How a credential field currently stands relative to a rotation.
 *
 * - `steady`   — one live value. No AWSPREVIOUS version, or it holds the same value.
 * - `rotating` — AWSCURRENT and AWSPREVIOUS differ. Both are served; callers that can
 *                dual-accept try current first, then previous. This is the window in
 *                which a third party may still be handing back tokens minted against
 *                the old value.
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
    /** AWS version id of the AWSCURRENT version the value came from. */
    versionId: string
    /** When this provider's secret was last read from Secrets Manager. */
    fetchedAt: string
}

/** A whole provider's fields, as loaded from one AWS secret. */
export interface ProviderSnapshot {
    provider: string
    fetchedAt: string
    versionId: string
    /** ISO-8601 timestamp of when the AWSCURRENT version was created. */
    currentActivatedAt: string | null
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
    /** Providers this deployment may ever obtain, or '*' for all of them. */
    allowedProviders: readonly string[] | '*'
    /** The exact keys this one request asked for, from the token's `keys` claim. */
    requestedKeys: readonly string[]
}

/** Per-key outcome, used for both metrics and the usage rollup. */
export type ResolveOutcome = 'ok' | 'denied' | 'missing' | 'recovery'
