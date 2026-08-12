/**
 * Where a secret stands relative to a rotation.
 *
 * - `steady`: one live value, with no `<KEY>_FALLBACKS` sibling holding a different one.
 * - `rotating`: the sibling holds a different value, and both are served, because a third
 *   party may still hand back tokens minted against the old one.
 * - `recovery`: the value is known-burned with no replacement yet, so nothing is served and
 *   callers raise a typed error rather than calling out with a secret that cannot work.
 */
export type SecretState = 'steady' | 'rotating' | 'recovery'

/** One secret as the mount holds it. */
export interface Secret {
    state: SecretState
    /** Absent only in `recovery`. */
    value?: string
    /** Present only in `rotating`. */
    previous?: string
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
