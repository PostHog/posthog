import type { AuthState, StoredAccount } from '@/auth/authStore'

type LabeledAccount = Pick<StoredAccount, 'key' | 'host' | 'region' | 'user'>

export function hostName(host: string): string {
    return host.replace(/^https?:\/\//, '')
}

/** "US", "EU", or the host name of a self-hosted instance. */
export function regionText(account: Pick<StoredAccount, 'host' | 'region'>): string {
    if (account.region === 'us') {
        return 'US'
    }
    if (account.region === 'eu') {
        return 'EU'
    }
    return hostName(account.host)
}

/**
 * How copy names an account: its email, plus the region only when another account on this phone has the same email.
 * Every confirmation and toast uses it, so one account always reads the same.
 */
export function accountLabel(account: LabeledAccount, accounts: readonly LabeledAccount[]): string {
    const email = account.user?.email
    if (!email) {
        return `the account on ${hostName(account.host)}`
    }
    const needle = email.toLowerCase()
    const shared = accounts.some((other) => other.key !== account.key && other.user?.email.toLowerCase() === needle)
    return shared ? `${email} (${regionText(account)})` : email
}

/** The active account first, then the others in the order they were added. */
export function orderedAccounts(accounts: readonly StoredAccount[], activeKey: string | null): StoredAccount[] {
    const active = accounts.find((account) => account.key === activeKey)
    return active ? [active, ...accounts.filter((account) => account !== active)] : [...accounts]
}

/** The account the store switches to after `leavingKey` signs out: the most recently used one that can sign in. */
export function nextAccountAfterSignOut(accounts: readonly StoredAccount[], leavingKey: string): StoredAccount | null {
    return (
        accounts
            .filter((account) => !account.needsSignIn && account.key !== leavingKey)
            .sort((a, b) => b.lastUsedAt - a.lastUsedAt)[0] ?? null
    )
}

/** The account whose active session expired, while the user is signed out and it still needs a sign-in. */
export function sessionEndedAccount(
    state: Pick<AuthState, 'accounts' | 'expiredAccountKey' | 'status'>
): StoredAccount | null {
    if (state.status !== 'signed_out' || state.expiredAccountKey === null) {
        return null
    }
    return state.accounts.find((account) => account.key === state.expiredAccountKey && account.needsSignIn) ?? null
}
