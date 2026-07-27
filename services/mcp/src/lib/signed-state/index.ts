/**
 * Public surface of the signed-state module.
 *
 * Import from `@/lib/signed-state` rather than reaching into individual
 * files — these exports are the supported API; everything else is an
 * implementation detail.
 */

export { DEFAULT_STATE_TTL_SECONDS, SIGNING_KEY_ENV_VAR } from './constants'
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
