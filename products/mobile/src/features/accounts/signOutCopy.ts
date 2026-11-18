import type { StoredAccount } from '@/auth/authStore'

import { accountLabel, nextAccountAfterSignOut } from './accountLabel'

export interface SignOutCopy {
    title: string
    body: string
}

const PUSH_STOPS = 'This device stops getting push notifications until you sign in again.'

/**
 * The in-place confirmation for signing out of `target`, one account key or every account. `activeKey` is null while
 * signed out, as on the session-ended screen, where the app switches to the next account after the sign out.
 */
export function signOutCopy(
    target: string | 'all',
    accounts: readonly StoredAccount[],
    activeKey: string | null
): SignOutCopy {
    if (target === 'all') {
        return { title: `Sign out of all ${accounts.length} accounts?`, body: PUSH_STOPS }
    }
    const account = accounts.find((candidate) => candidate.key === target)
    if (!account) {
        return { title: 'Sign out?', body: PUSH_STOPS }
    }
    const title = `Sign out of ${accountLabel(account, accounts)}?`
    const active = accounts.find((candidate) => candidate.key === activeKey)
    if (active && active.key !== target) {
        return {
            title,
            body: account.needsSignIn
                ? 'The account leaves this phone. Your other accounts stay signed in.'
                : `You stay signed in to ${accountLabel(active, accounts)}. Notifications keep coming from that account.`,
        }
    }
    const next = nextAccountAfterSignOut(accounts, target)
    if (next) {
        return {
            title,
            body: `The app switches to ${accountLabel(next, accounts)}, and notifications come from that account.`,
        }
    }
    return { title, body: active ? PUSH_STOPS : 'The account leaves this phone.' }
}
