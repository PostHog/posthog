/**
 * Hard-coded constants for the signed-state codec.
 *
 * None of these are env-configurable on purpose. They define the security
 * envelope that callers (today: the typed-confirm two-tool paradigm) rely
 * on. Tuning them is a deliberate code change, not a deployment knob.
 */

/**
 * Default TTL on a signed state token, in seconds. 15 minutes gives the user
 * time to review a large prepared payload (a full scout definition, say)
 * before typing "confirm" — 5 minutes proved too short for that in practice —
 * while still bounding the window a leaked or guessed token is usable. Matches
 * the 15-minute expiry of the workflows blast-radius confirm token.
 */
export const DEFAULT_STATE_TTL_SECONDS = 900

/** Minimum acceptable length of the signing key, in bytes (HMAC-SHA256 output size). */
export const SIGNING_KEY_MIN_BYTES = 32

/** Redis key prefix for the single-use nonce ledger. */
export const NONCE_KEY_PREFIX = 'mcp:signed-state:nonce'

/** Redis key prefix for stashed prepare payloads awaiting execute. */
export const PAYLOAD_KEY_PREFIX = 'mcp:signed-state:payload'

/** Redis key prefix for the per-user stashed-bytes quota window. */
export const PAYLOAD_QUOTA_KEY_PREFIX = 'mcp:signed-state:payload-quota'

/**
 * Extra lifetime a stashed payload gets beyond its token's TTL. Ensures the
 * Redis entry never expires before the token does under clock skew — an
 * expired token must refuse as 'expired' (from the JWT check), not as
 * 'already used' because the stash entry vanished first.
 */
export const PAYLOAD_STASH_TTL_MARGIN_SECONDS = 30

/**
 * Maximum serialized size of a single stashed prepare payload, in bytes.
 * Matches the Hono dispatcher's 1 MiB request-body cap (`MAX_BODY_BYTES`),
 * so it never rejects args the transport can deliver — anything tighter
 * would refuse scout definitions the backend accepts (1 MB per body/file).
 * It exists as a backstop so a future request-limit raise can't silently
 * widen Redis retention. The aggregate exposure is bounded separately by
 * `STASH_QUOTA_BYTES_PER_WINDOW`.
 */
export const MAX_STASHED_PAYLOAD_BYTES = 1_048_576

/**
 * Aggregate bytes one user may stash per quota window. Stashed payloads
 * share Redis with session and rate-limit state, so per-payload and
 * per-request limits alone still allow a caller at the rate limit to
 * retain gigabytes within one token TTL. 20 MiB per window is far above
 * legitimate use (a burst of large scout definitions is still a few MiB)
 * while capping worst-case retention per user near the quota. The window
 * spans the payload TTL, so the counter outlives every entry it charged
 * for; it is not decremented on execute — a consumed confirmation still
 * counts until the window rolls. Fixed windows admit a boundary burst:
 * filling the quota at the end of one window and again at the start of
 * the next transiently retains up to 2× this value. That is accepted —
 * the alternative (refreshing the expiry on every charge) never resets
 * for a steadily active caller, eventually locking out legitimate use.
 */
export const STASH_QUOTA_BYTES_PER_WINDOW = 20 * 1_048_576

/** Env var name. */
export const SIGNING_KEY_ENV_VAR = 'MCP_SIGNED_STATE_KEY'
