import type { StoredAccount } from '@/auth/authStore'

import { accountLabel, sessionEndedAccount } from './accountLabel'
import { signOutCopy } from './signOutCopy'
import { EU_ACCOUNT, SELF_HOSTED_ACCOUNT, US_ACCOUNT } from './testAccounts'

const PUSH_STOPS = 'This device stops getting push notifications until you sign in again.'
const ALL = [US_ACCOUNT, EU_ACCOUNT, SELF_HOSTED_ACCOUNT]

describe('account copy', () => {
    test.each<[string, StoredAccount, StoredAccount[], string]>([
        ['a unique email stands alone', US_ACCOUNT, [US_ACCOUNT, SELF_HOSTED_ACCOUNT], 'maya@example.com'],
        ['a shared email adds the Cloud region', EU_ACCOUNT, ALL, 'maya@example.com (EU)'],
        [
            'a shared email on a self-hosted instance adds the host',
            { ...SELF_HOSTED_ACCOUNT, user: US_ACCOUNT.user },
            [US_ACCOUNT, { ...SELF_HOSTED_ACCOUNT, user: US_ACCOUNT.user }],
            'maya@example.com (posthog.example.org)',
        ],
        [
            'an account not loaded yet falls back to its host',
            { ...EU_ACCOUNT, user: null },
            ALL,
            'the account on eu.posthog.com',
        ],
    ])('accountLabel: %s', (_name, account, accounts, expected) => {
        expect(accountLabel(account, accounts)).toBe(expected)
    })

    test.each<[string, string | 'all', StoredAccount[], string | null, string, string]>([
        [
            'the active account names the most recently used account that can sign in',
            US_ACCOUNT.key,
            [{ ...SELF_HOSTED_ACCOUNT, lastUsedAt: 9 }, EU_ACCOUNT, US_ACCOUNT],
            US_ACCOUNT.key,
            'Sign out of maya@example.com (US)?',
            'The app switches to maya@example.com (EU), and notifications come from that account.',
        ],
        [
            'the only account keeps the push warning',
            US_ACCOUNT.key,
            [US_ACCOUNT],
            US_ACCOUNT.key,
            'Sign out of maya@example.com?',
            PUSH_STOPS,
        ],
        [
            'an inactive account keeps the active one',
            EU_ACCOUNT.key,
            ALL,
            US_ACCOUNT.key,
            'Sign out of maya@example.com (EU)?',
            'You stay signed in to maya@example.com (US). Notifications keep coming from that account.',
        ],
        [
            'an inactive account that needs a sign-in only leaves',
            SELF_HOSTED_ACCOUNT.key,
            ALL,
            US_ACCOUNT.key,
            'Sign out of maya@example.org?',
            'The account leaves this phone. Your other accounts stay signed in.',
        ],
        [
            'the expired account while signed out names the account that becomes active',
            SELF_HOSTED_ACCOUNT.key,
            ALL,
            null,
            'Sign out of maya@example.org?',
            'The app switches to maya@example.com (US), and notifications come from that account.',
        ],
        ['every account counts them', 'all', ALL, US_ACCOUNT.key, 'Sign out of all 3 accounts?', PUSH_STOPS],
    ])('signOutCopy: %s', (_name, target, accounts, activeKey, title, body) => {
        expect(signOutCopy(target, accounts, activeKey)).toEqual({ title, body })
    })

    test.each<[string, Parameters<typeof sessionEndedAccount>[0], StoredAccount | null]>([
        [
            'the expired account was the last one active',
            {
                status: 'signed_out',
                signedOutReason: 'expired',
                accounts: [US_ACCOUNT, { ...SELF_HOSTED_ACCOUNT, lastUsedAt: 9 }],
            },
            { ...SELF_HOSTED_ACCOUNT, lastUsedAt: 9 },
        ],
        [
            'an older expired account is not the one that just ended',
            { status: 'signed_out', signedOutReason: 'expired', accounts: [US_ACCOUNT, SELF_HOSTED_ACCOUNT] },
            null,
        ],
        [
            'a sign out on purpose shows no session-ended screen',
            { status: 'signed_out', signedOutReason: null, accounts: [{ ...SELF_HOSTED_ACCOUNT, lastUsedAt: 9 }] },
            null,
        ],
    ])('sessionEndedAccount: %s', (_name, state, expected) => {
        expect(sessionEndedAccount(state)).toEqual(expected)
    })
})
