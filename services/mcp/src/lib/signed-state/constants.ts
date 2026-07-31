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

/**
 * Extra lifetime a stashed payload gets beyond its token's TTL. Ensures the
 * Redis entry never expires before the token does under clock skew — an
 * expired token must refuse as 'expired' (from the JWT check), not as
 * 'already used' because the stash entry vanished first.
 */
export const PAYLOAD_STASH_TTL_MARGIN_SECONDS = 30

/**
 * Maximum serialized size of a stashed prepare payload, in bytes. Stashed
 * payloads live in shared Redis for the token TTL, so without a cap an
 * authenticated caller could retain rate-limit × TTL × request-size bytes
 * and pressure eviction of session and rate-limit state. 256 KiB is far
 * above any legitimate confirmed action (the largest, a scout definition
 * with reference files, runs tens of KiB) while bounding worst-case
 * retention per user to the low hundreds of MB.
 */
export const MAX_STASHED_PAYLOAD_BYTES = 256 * 1024

/** Env var name. */
export const SIGNING_KEY_ENV_VAR = 'MCP_SIGNED_STATE_KEY'
