/**
 * Public surface of the signed-state module.
 *
 * Import from `@/lib/signed-state` rather than reaching into individual
 * files — these exports are the supported API; everything else is an
 * implementation detail.
 */

export {
    DEFAULT_STATE_TTL_SECONDS,
    MAX_STASHED_PAYLOAD_BYTES,
    PAYLOAD_STASH_TTL_MARGIN_SECONDS,
    SIGNING_KEY_ENV_VAR,
    STASH_QUOTA_BYTES_PER_WINDOW,
} from './constants'
export {
    SignedStateAlreadyConsumed,
    SignedStateError,
    SignedStateExpired,
    SignedStateMalformed,
    SignedStatePurposeMismatch,
    SignedStateSignatureInvalid,
    SignedStateUserMismatch,
} from './errors'
export { loadSigningKeyFromEnv, SignedStateCodec } from './codec'
export type { SignedStateClaims, SignedStateCodecOptions } from './codec'
export { NonceLedger } from './nonce-ledger'
export type { NonceLedgerRedis } from './nonce-ledger'
export { PayloadStash } from './payload-stash'
export type { PayloadStashRedis } from './payload-stash'
