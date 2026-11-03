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

export interface SessionIdentity {
    readonly host: string
    readonly clientId: string | null
    readonly method: SessionTokens['kind']
    readonly userUuid: string
}

interface SessionEnvelope {
    version: 1
    identity: SessionIdentity
    tokens: SessionTokens
}

let identity: SessionIdentity | null = null

export function getSessionIdentity(): SessionIdentity | null {
    return identity
}

function storedSession(tokens: SessionTokens, owner: SessionIdentity | null): string {
    if (!owner || owner.method !== tokens.kind) {
        throw new Error('Session identity is required to persist credentials')
    }
    return JSON.stringify({ version: 1, identity: owner, tokens } satisfies SessionEnvelope)
}

const STORAGE_KEY = 'posthog_mobile_session'

let current: SessionTokens | null = null
let generation = 0
let storageQueue: Promise<void> = Promise.resolve()

function serializeStorage<T>(work: () => Promise<T>): Promise<T> {
    const result = storageQueue.then(work, work)
    storageQueue = result.then(
        () => undefined,
        () => undefined
    )
    return result
}

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
export function setSessionTokens(tokens: SessionTokens | null, owner: SessionIdentity | null = null): void {
    identity = owner ? Object.freeze({ ...owner }) : null
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
    const envelope = parsed as Partial<SessionEnvelope> | null
    const owner = envelope?.identity
    const tokens = envelope?.version === 1 ? toSessionTokens(envelope.tokens) : null
    const validOwner =
        owner &&
        typeof owner.host === 'string' &&
        owner.host.length > 0 &&
        typeof owner.userUuid === 'string' &&
        owner.userUuid.length > 0 &&
        owner.method === tokens?.kind &&
        (owner.method === 'oauth'
            ? typeof owner.clientId === 'string' && owner.clientId.length > 0
            : owner.clientId === null)
    current = validOwner ? tokens : null
    identity = validOwner ? Object.freeze({ ...owner }) : null
    generation += 1
    return current
}

/**
 * Keeps the generation, because a refresh saves its rotated tokens into the same session. A new session calls
 * `setSessionTokens` first.
 */
export async function saveTokens(tokens: SessionTokens, owner: SessionIdentity | null = identity): Promise<void> {
    await serializeStorage(async () => {
        await writeItem(STORAGE_KEY, storedSession(tokens, owner))
        current = tokens
        identity = owner ? Object.freeze({ ...owner }) : null
    })
}

/** Persists and publishes a new session in one storage turn, after its account has loaded. */
export async function commitSessionTokens(
    tokens: SessionTokens,
    owner: SessionIdentity,
    canPublish: () => boolean,
    publish: () => void
): Promise<boolean> {
    return serializeStorage(async () => {
        if (!canPublish()) {
            return false
        }
        await writeItem(STORAGE_KEY, storedSession(tokens, owner))
        if (!canPublish()) {
            // A sign out or later sign-in started while SecureStore was writing. Restore the current session before
            // the queued transition can run, so a relaunch never pairs the earlier candidate with the later host.
            if (current) {
                await writeItem(STORAGE_KEY, storedSession(current, identity))
            } else {
                await deleteItem(STORAGE_KEY)
            }
            return false
        }
        setSessionTokens(tokens, owner)
        publish()
        return true
    })
}

/** A refresh queued behind a new sign-in must not overwrite the new session's stored token. */
export async function saveRefreshedTokens(tokens: SessionTokens, expectedGeneration: number): Promise<boolean> {
    return serializeStorage(async () => {
        if (generation !== expectedGeneration) {
            return false
        }
        await writeItem(STORAGE_KEY, storedSession(tokens, identity))
        if (generation !== expectedGeneration) {
            return false
        }
        current = tokens
        return true
    })
}

export async function clearTokens(): Promise<void> {
    current = null
    identity = null
    generation += 1
    try {
        await serializeStorage(() => deleteItem(STORAGE_KEY))
    } catch {
        // A failed delete leaves a token that the next restore tries and the server rejects.
    }
}
