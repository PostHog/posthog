/**
 * Where a credential field stands relative to a rotation.
 *
 * - `steady`: one live value, with no `<KEY>_FALLBACKS` sibling holding a different one.
 * - `rotating`: the sibling holds a different value, and both are served, because a third
 *   party may still hand back tokens minted against the old one.
 * - `recovery`: the value is known-burned with no replacement yet, so nothing is served and
 *   callers raise a typed error rather than calling out with a credential that cannot work.
 */
export type SecretState = 'steady' | 'rotating' | 'recovery'

/** One credential field as the store resolved it. */
export interface ResolvedSecret {
    state: SecretState
    /** Absent only in `recovery`. */
    value?: string
    /** Present only in `rotating`. */
    previous?: string
    versionId: string
    /** When the mount this value came from was last read. */
    fetchedAt: string
}

/** Every credential field, as loaded from the one integration-service secret. */
export interface SecretsSnapshot {
    fetchedAt: string
    /** Hash of the whole mounted key set. Identifies the content, not an AWS version. */
    versionId: string
    /**
     * When this content was first seen, from the version table so every replica agrees and a
     * restart does not reset it. It is the threshold safeToRetirePrevious compares reads
     * against. Not per-key: an unrelated edit moves it forward and only delays a verdict.
     */
    changedAt: string | null
    secrets: Record<string, ResolvedSecret>
}

/** What a verified request is allowed to do, and who to attribute it to. */
export interface CallerIdentity {
    /**
     * The pod set that signed the token, established by which key verified it. This is the
     * authenticated identity and the authorization boundary.
     */
    deployment: string
    /**
     * The product code path that wanted the credential. Caller-supplied, not verified, and
     * grants nothing. Collapsed to a recognised name or a constant, so it is safe as a
     * metric label.
     */
    product: string
    /** The exact keys this one request asked for, from the token's `keys` claim. */
    requestedKeys: readonly string[]
}

/** Per-key outcome, used for both metrics and the usage rollup. */
export type ResolveOutcome = 'ok' | 'missing' | 'recovery'
