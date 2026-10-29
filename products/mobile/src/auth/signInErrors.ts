import { ApiError, NotSignedInError } from '@/api/client'

import type { AuthMethod } from './authStore'
import { OAuthError, type OAuthErrorKind } from './oauth'

export class SignInInputError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'SignInInputError'
    }
}

export type AccountLoadKind = 'rejected' | 'forbidden' | 'api_error' | 'network' | 'unknown'

export function accountLoadKind(error: unknown): AccountLoadKind {
    if (error instanceof NotSignedInError) {
        return 'rejected'
    }
    if (error instanceof ApiError) {
        return error.status === 403 ? 'forbidden' : 'api_error'
    }
    if (error instanceof TypeError) {
        return 'network'
    }
    return 'unknown'
}

/** The new credentials worked for the token exchange, but the account bootstrap failed. `message` is user-facing. */
export class AccountLoadError extends Error {
    readonly kind: AccountLoadKind

    constructor(kind: AccountLoadKind, message: string) {
        super(message)
        this.name = 'AccountLoadError'
        this.kind = kind
    }
}

export type SignInFailureReason =
    | Exclude<OAuthErrorKind, 'session_expired'>
    | 'invalid_input'
    | 'invalid_key'
    | 'account_rejected'
    | 'account_forbidden'
    | 'account_load'
    | 'unknown'

const ACCOUNT_REASONS: Record<AccountLoadKind, SignInFailureReason> = {
    rejected: 'account_rejected',
    forbidden: 'account_forbidden',
    api_error: 'account_load',
    network: 'network',
    unknown: 'unknown',
}

/** A fixed enum for analytics, so no error text leaves the device. */
export function signInFailureReason(error: unknown, method: AuthMethod): SignInFailureReason {
    if (error instanceof SignInInputError) {
        return 'invalid_input'
    }
    if (error instanceof OAuthError) {
        return error.kind === 'session_expired' ? 'unknown' : error.kind
    }
    if (error instanceof AccountLoadError) {
        return error.kind === 'rejected' && method === 'personal_api_key' ? 'invalid_key' : ACCOUNT_REASONS[error.kind]
    }
    return 'unknown'
}
