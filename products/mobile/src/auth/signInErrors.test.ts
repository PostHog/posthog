import { ApiError, NotSignedInError } from '@/api/client'

import type { AuthMethod } from './authStore'
import { OAuthError } from './oauth'
import {
    AccountLoadError,
    accountLoadKind,
    type SignInFailureReason,
    SignInInputError,
    signInFailureReason,
} from './signInErrors'

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }))
jest.mock('expo-auth-session', () => ({ AuthRequest: jest.fn(), makeRedirectUri: () => 'posthog://callback' }))

function accountError(cause: unknown): AccountLoadError {
    return new AccountLoadError(accountLoadKind(cause), 'Shown to the user')
}

describe('signInFailureReason', () => {
    test.each<[string, unknown, AuthMethod, SignInFailureReason]>([
        ['an invalid host', new SignInInputError('Enter a host'), 'oauth', 'invalid_input'],
        ['a cancelled browser', new OAuthError('cancelled'), 'oauth', 'cancelled'],
        ['a rejected personal API key', accountError(new NotSignedInError()), 'personal_api_key', 'invalid_key'],
        ['a rejected OAuth session', accountError(new NotSignedInError()), 'oauth', 'account_rejected'],
        ['a 403 on the account', accountError(new ApiError(403, {})), 'oauth', 'account_forbidden'],
        ['a 500 on the account', accountError(new ApiError(500, {})), 'oauth', 'account_load'],
        ['no connection for the account', accountError(new TypeError('Network request failed')), 'oauth', 'network'],
        ['anything else', new Error('boom'), 'oauth', 'unknown'],
    ])('%s', (_name, error, method, expected) => {
        expect(signInFailureReason(error, method)).toBe(expected)
    })
})
