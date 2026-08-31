/**
 * Where a secret stands relative to a rotation.
 *
 * - `steady`: one live value, with no `<KEY>_FALLBACKS` sibling holding a different one.
 * - `rotating`: the sibling holds a different value, and both are served, so a caller can use
 *   the staged replacement before it goes live — useful when the third party has already been
 *   rotated and the live value no longer works there.
 * - `recovery`: the value is known-burned with no replacement yet, so nothing is served and
 *   callers raise a typed error rather than calling out with a secret that cannot work.
 */
export type SecretState = 'steady' | 'rotating' | 'recovery'

/** One secret as the mount holds it. */
export interface Secret {
    state: SecretState
    /** Absent only in `recovery`. */
    value?: string
    /**
     * The other value the mount serves for this key, present only in `rotating`.
     *
     * It is the INCOMING value, not the outgoing one: a rotation stages the new value in the
     * sibling while `value` stays live, and promoting it moves the staged value into `value` and
     * drops the sibling. So a key with a sibling is one whose replacement is staged and accepted
     * but not yet live.
     */
    incoming?: string
    versionId: string
    /** When the mount this value came from was last read. */
    fetchedAt: string
}

/** Every secret on the mount, as one read of it saw them. */
export interface MountedSecrets {
    fetchedAt: string
    /** Hash of the whole mounted key set, so unchanged content keeps one id. */
    versionId: string
    secrets: Record<string, Secret>
}

/** What a verified request is allowed to do, and who to attribute it to. */
export interface CallerIdentity {
    /**
     * The pod set that signed the token, established by which key verified it. This is the
     * authenticated identity and the authorization boundary.
     */
    deployment: string
    /**
     * The product code path that wanted the secret. Caller-supplied and unverified, so
     * it reaches the audit log and nothing else — never a metric label.
     */
    caller: string
    /** The exact keys this one request asked for, from the token's `keys` claim. */
    requestedKeys: readonly string[]
}

/** Per-key outcome, used for both metrics and the usage rollup. */
export type ResolveOutcome = 'ok' | 'missing' | 'recovery'

export interface Lifecycle {
    shuttingDown: boolean
    ready: boolean
}
