import * as Crypto from 'expo-crypto'

/** One PostHog login on this device, as account-removed tasks receive it. */
export interface AccountRef {
    key: string
    host: string
    userUuid: string
}

const SECURE_STORE_KEY = /^[A-Za-z0-9._-]+$/

/**
 * The stable key of one user on one host. It is a SHA-256 hex digest, so it fits SecureStore key rules and names no
 * host or email. The offline read cache and chat drafts build their storage keys from these exact bytes, so a change
 * to the input or the digest orphans every account's saved data.
 */
export async function accountKey(host: string, userUuid: string): Promise<string> {
    const digest = await Crypto.digestStringAsync(
        Crypto.CryptoDigestAlgorithm.SHA256,
        JSON.stringify([host.replace(/\/$/, ''), userUuid])
    )
    // An empty digest would give every account the same token slot.
    if (!SECURE_STORE_KEY.test(digest)) {
        throw new Error('The account key digest is not a usable storage key.')
    }
    return digest
}

/**
 * Splits data that an app version before multi-account stored without an owner. Its keys start with `{host}|`. Only
 * the session that launch restored from that version can own it, and only the entries on its host.
 */
export function legacyEntriesFor<T>(
    legacy: Record<string, T>,
    account: AccountRef | null
): { owned: Record<string, T>; dropped: T[] } {
    const owned: Record<string, T> = {}
    const dropped: T[] = []
    for (const [key, value] of Object.entries(legacy)) {
        if (account && key.startsWith(`${account.host.replace(/\/$/, '')}|`)) {
            owned[key] = value
        } else {
            dropped.push(value)
        }
    }
    return { owned, dropped }
}
