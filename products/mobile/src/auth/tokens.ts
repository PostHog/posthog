import * as SecureStore from 'expo-secure-store'
import { Platform } from 'react-native'

export interface SessionTokens {
    kind: 'oauth' | 'personal_api_key'
    accessToken: string
    refreshToken: string | null
    /** Epoch ms when the access token stops working, or null when it does not expire. */
    expiresAt: number | null
}

const STORAGE_KEY = 'posthog_mobile_session'

let current: SessionTokens | null = null

export function getSessionTokens(): SessionTokens | null {
    return current
}

/** Changes the in-memory tokens only. Call `saveTokens` to keep them across launches. */
export function setSessionTokens(tokens: SessionTokens | null): void {
    current = tokens
}

// expo-secure-store has no web implementation. The web build is a dev and preview target, so it keeps tokens in
// localStorage in dev builds and in memory otherwise, where a reload signs out.
const webMemory = new Map<string, string>()

function webStorage(): Storage | null {
    if (!__DEV__ || typeof localStorage === 'undefined') {
        return null
    }
    return localStorage
}

async function readItem(key: string): Promise<string | null> {
    if (Platform.OS === 'web') {
        return webStorage()?.getItem(key) ?? webMemory.get(key) ?? null
    }
    return SecureStore.getItemAsync(key)
}

async function writeItem(key: string, value: string): Promise<void> {
    if (Platform.OS === 'web') {
        const storage = webStorage()
        if (storage) {
            storage.setItem(key, value)
        } else {
            webMemory.set(key, value)
        }
        return
    }
    await SecureStore.setItemAsync(key, value)
}

async function deleteItem(key: string): Promise<void> {
    if (Platform.OS === 'web') {
        webStorage()?.removeItem(key)
        webMemory.delete(key)
        return
    }
    await SecureStore.deleteItemAsync(key)
}

function isSessionTokens(value: unknown): value is SessionTokens {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const record = value as Record<string, unknown>
    return (
        (record.kind === 'oauth' || record.kind === 'personal_api_key') &&
        typeof record.accessToken === 'string' &&
        (record.refreshToken === null || typeof record.refreshToken === 'string') &&
        (record.expiresAt === null || typeof record.expiresAt === 'number')
    )
}

export async function loadTokens(): Promise<SessionTokens | null> {
    let raw: string | null = null
    try {
        raw = await readItem(STORAGE_KEY)
    } catch {
        raw = null
    }
    let parsed: unknown = null
    try {
        parsed = raw ? JSON.parse(raw) : null
    } catch {
        parsed = null
    }
    current = isSessionTokens(parsed) ? parsed : null
    return current
}

export async function saveTokens(tokens: SessionTokens): Promise<void> {
    current = tokens
    await writeItem(STORAGE_KEY, JSON.stringify(tokens))
}

export async function clearTokens(): Promise<void> {
    current = null
    try {
        await deleteItem(STORAGE_KEY)
    } catch {
        // A failed delete leaves a token that the next restore tries and the server rejects.
    }
}
