import { ApiError, NotSignedInError } from '@/api/client'
import { TransportError } from '@/api/transport'

import type { AuthMethod, StoredAccount } from './authStore'
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
    if (error instanceof TransportError) {
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

/** The browser returned an account that is already on this device. It was usually still signed in to the web app. */
export class AccountAlreadyAddedError extends Error {
    readonly key: string
    readonly email: string
    readonly host: string

    constructor(key: string, email: string, host: string) {
        super(
            `${email} is already signed in on this device. To add another account, sign out of PostHog in your browser, then try again.`
        )
        this.name = 'AccountAlreadyAddedError'
        this.key = key
        this.email = email
        this.host = host
    }
}

/** The account's credentials are gone or the server refused them, so it needs a new sign-in. */
export class AccountNeedsSignInError extends Error {
    readonly key: string
    readonly email: string | null
    readonly host: string

    constructor(account: Pick<StoredAccount, 'key' | 'host' | 'user'>) {
        const email = account.user?.email ?? null
        super(
            email
                ? `Your session for ${email} ended. Sign in again to use this account.`
                : 'The session for this account ended. Sign in again to use it.'
        )
        this.name = 'AccountNeedsSignInError'
        this.key = account.key
        this.email = email
        this.host = account.host
    }
}

/** The account's slot could not be read, such as before the first unlock. The account and its slot stay as they are. */
export class AccountUnavailableError extends Error {
    readonly key: string

    constructor(account: Pick<StoredAccount, 'key' | 'host' | 'user'>) {
        const email = account.user?.email
        super(
            email
                ? `Couldn't read the sign-in for ${email} on this phone. Try again, or sign in again.`
                : "Couldn't read the sign-in for this account on this phone. Try again, or sign in again."
        )
        this.name = 'AccountUnavailableError'
        this.key = account.key
    }
}

export type SignInFailureReason =
    | Exclude<OAuthErrorKind, 'session_expired'>
    | 'invalid_input'
    | 'invalid_key'
    | 'account_rejected'
    | 'account_forbidden'
    | 'account_load'
    | 'account_already_added'
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
    if (error instanceof AccountAlreadyAddedError) {
        return 'account_already_added'
    }
    if (error instanceof AccountLoadError) {
        return error.kind === 'rejected' && method === 'personal_api_key' ? 'invalid_key' : ACCOUNT_REASONS[error.kind]
    }
    return 'unknown'
}
