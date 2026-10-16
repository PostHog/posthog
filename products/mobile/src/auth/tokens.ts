import * as SecureStore from 'expo-secure-store'
import { Platform } from 'react-native'

export interface SessionTokens {
    kind: 'oauth' | 'personal_api_key'
    accessToken: string
    refreshToken: string | null
    /** Epoch ms when the access token stops working, or null when it does not expire. */
    expiresAt: number | null
    /**
     * The scopes the server granted, from the token response. Null for a personal API key and for a session stored
     * before the app recorded them, where only a 403 tells which scope is missing.
     */
    grantedScopes: string[] | null
    /**
     * The scopes the sign-in asked for. A scope asked for but not granted is outside the OAuth application's ceiling,
     * so signing in again gets the same grant. Null for a personal API key and for a session stored before the app
     * recorded them.
     */
    requestedScopes: string[] | null
}

const STORAGE_KEY = 'posthog_mobile_session'

let current: SessionTokens | null = null
let generation = 0

export function getSessionTokens(): SessionTokens | null {
    return current
}

/**
 * Identifies the session that `getSessionTokens` belongs to. It changes on sign in, sign out and restore, but not when
 * a refresh rotates the tokens. Async work captures it before it awaits and compares after, so that a response from
 * an earlier session never reads, stores or sends the tokens of a later one.
 */
export function sessionGeneration(): number {
    return generation
}

/**
 * Changes the in-memory tokens only and starts a new session generation. Call `saveTokens` to keep them across
 * launches.
 */
export function setSessionTokens(tokens: SessionTokens | null): void {
    current = tokens
    generation += 1
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

function scopesOf(value: unknown): string[] | null {
    return Array.isArray(value) && value.every((scope) => typeof scope === 'string') ? value : null
}

function toSessionTokens(value: unknown): SessionTokens | null {
    if (typeof value !== 'object' || value === null) {
        return null
    }
    const record = value as Record<string, unknown>
    const valid =
        (record.kind === 'oauth' || record.kind === 'personal_api_key') &&
        typeof record.accessToken === 'string' &&
        (record.refreshToken === null || typeof record.refreshToken === 'string') &&
        (record.expiresAt === null || typeof record.expiresAt === 'number')
    // Sessions stored before the app recorded scopes have no `grantedScopes` or `requestedScopes`, which read as unknown.
    return valid
        ? ({
              ...record,
              grantedScopes: scopesOf(record.grantedScopes),
              requestedScopes: scopesOf(record.requestedScopes),
          } as SessionTokens)
        : null
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
    current = toSessionTokens(parsed)
    generation += 1
    return current
}

/**
 * Keeps the generation, because a refresh saves its rotated tokens into the same session. A new session calls
 * `setSessionTokens` first.
 */
export async function saveTokens(tokens: SessionTokens): Promise<void> {
    current = tokens
    await writeItem(STORAGE_KEY, JSON.stringify(tokens))
}

export async function clearTokens(): Promise<void> {
    current = null
    generation += 1
    try {
        await deleteItem(STORAGE_KEY)
    } catch {
        // A failed delete leaves a token that the next restore tries and the server rejects.
    }
}
