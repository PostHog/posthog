/**
 * Hard-coded constants for the 2026-07-28 protocol pipeline.
 *
 * None of these are env-configurable on purpose. They define the protocol
 * contract or the safety bounds the dispatcher enforces; changing them is a
 * code change reviewed by humans, not a deployment knob.
 */

/** The MCP protocol version this pipeline implements. */
export const PROTOCOL_VERSION_2026_07_28 = '2026-07-28' as const

/** Legacy protocol version accepted as an explicit opt-in to the legacy pipeline. */
export const PROTOCOL_VERSION_2025_06_18 = '2025-06-18' as const

/**
 * How long a `requestState` token stays valid after issue, in seconds.
 *
 * 10 minutes is a balance between human attention spans on a confirmation
 * modal (a few minutes is realistic; longer is rare) and bounding the
 * window a leaked or guessed token is usable. Tuned via the
 * `mcp_v2026_request_state_expired_total` counter — a sustained non-zero
 * rate is the signal to raise this.
 */
export const REQUEST_STATE_TTL_SECONDS = 600

/**
 * Maximum number of `InputRequiredResult` rounds for one logical tool call.
 *
 * Each round increments the `round` claim in `requestState`. The dispatcher
 * refuses to issue another input request when the incoming round counter
 * reaches this cap, preventing buggy tool loops or adversarial retries from
 * burning CPU/Redis indefinitely. 10 is generous for legitimate multi-step
 * flows (the SEP's ADO custom-rules example tops out at 3 rounds) and tight
 * enough to bound damage.
 */
export const MAX_REQUEST_STATE_ROUNDS = 10

/**
 * Minimum acceptable length of `MCP_REQUEST_STATE_SIGNING_KEY`, in bytes.
 * 32 bytes (256 bits) matches the HMAC-SHA256 output size; shorter keys
 * lose security without adding convenience.
 */
export const SIGNING_KEY_MIN_BYTES = 32

/** HTTP header carrying the protocol version (SEP-2575, SEP-2243). */
export const PROTOCOL_VERSION_HEADER = 'mcp-protocol-version'

/** HTTP header carrying the JSON-RPC method name (SEP-2243). */
export const METHOD_HEADER = 'mcp-method'

/** HTTP header carrying the tool/resource/prompt name (SEP-2243). */
export const NAME_HEADER = 'mcp-name'

/** Required _meta keys on every request payload (SEP-2575). */
export const META_KEY_PROTOCOL_VERSION = 'io.modelcontextprotocol/protocolVersion'
export const META_KEY_CLIENT_INFO = 'io.modelcontextprotocol/clientInfo'
export const META_KEY_CLIENT_CAPABILITIES = 'io.modelcontextprotocol/clientCapabilities'
export const META_KEY_LOG_LEVEL = 'io.modelcontextprotocol/logLevel'

/** Env vars for the signing key. */
export const SIGNING_KEY_ENV_VAR = 'MCP_REQUEST_STATE_SIGNING_KEY'
export const SIGNING_KEY_OLD_ENV_VAR = 'MCP_REQUEST_STATE_SIGNING_KEY_OLD'
