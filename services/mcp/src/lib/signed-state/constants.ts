/**
 * Hard-coded constants for the signed-state codec.
 *
 * None of these are env-configurable on purpose. They define the security
 * envelope that callers (today: the typed-confirm two-tool paradigm) rely
 * on. Tuning them is a deliberate code change, not a deployment knob.
 */

/**
 * Default TTL on a signed state token, in seconds. 5 minutes is long enough
 * for a model to surface the prepare result to the user and for the user to
 * reply with "confirm", short enough to bound the window a leaked or guessed
 * token is usable.
 */
export const DEFAULT_STATE_TTL_SECONDS = 300

/** Minimum acceptable length of the signing key, in bytes (HMAC-SHA256 output size). */
export const SIGNING_KEY_MIN_BYTES = 32

/** Redis key prefix for the single-use nonce ledger. */
export const NONCE_KEY_PREFIX = 'mcp:signed-state:nonce'

/** Env var name. */
export const SIGNING_KEY_ENV_VAR = 'MCP_SIGNED_STATE_KEY'
