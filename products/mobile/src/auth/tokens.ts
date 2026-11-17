import * as SecureStore from 'expo-secure-store'
import { Platform } from 'react-native'

import { accountKey } from './accountKey'

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

/** The content of one account's token slot. */
export interface StoredSession {
    key: string
    identity: SessionIdentity
    tokens: SessionTokens
}

interface SessionEnvelope {
    version: 1
    identity: SessionIdentity
    tokens: SessionTokens
}

interface AccountIndex {
    version: 1
    active: string | null
    keys: string[]
}

// App versions before multi-account kept their one session here. Restore moves it into its account's slot.
const LEGACY_SESSION_KEY = 'posthog_mobile_session'
const SLOT_PREFIX = 'posthog_mobile_session.'
// SecureStore cannot list its keys, and the iOS keychain outlives a reinstall while AsyncStorage does not, so this
// item is the record of which slots exist and which one is active.
const INDEX_KEY = 'posthog_mobile_accounts'

function slotKey(key: string): string {
    return `${SLOT_PREFIX}${key}`
}

let identity: SessionIdentity | null = null
let current: SessionTokens | null = null
let activeKey: string | null = null
let generation = 0
let storageQueue: Promise<void> = Promise.resolve()

export function getSessionIdentity(): SessionIdentity | null {
    return identity
}

export function getSessionTokens(): SessionTokens | null {
    return current
}

/** The account key of the slot that the in-memory session belongs to. */
export function getSessionAccountKey(): string | null {
    return activeKey
}

/**
 * Identifies the session that `getSessionTokens` belongs to. It changes on sign in, sign out, restore and account
 * switch, but not when a refresh rotates the tokens. Async work captures it before it awaits and compares after, so
 * that a response from an earlier session never reads, stores or sends the tokens of a later one.
 */
export function sessionGeneration(): number {
    return generation
}

/** `session`: a sign in, sign out, restore or account switch. `refresh`: the same session with rotated tokens. */
export type SessionTokensChange = 'session' | 'refresh'

const tokenListeners = new Set<(change: SessionTokensChange) => void>()

/**
 * Calls `listener` after the in-memory tokens change. Features that keep a copy of the session, such as the home screen
 * widget, subscribe here so auth does not import them.
 */
export function onSessionTokensChanged(listener: (change: SessionTokensChange) => void): () => void {
    tokenListeners.add(listener)
    return () => {
        tokenListeners.delete(listener)
    }
}

function publishTokens(change: SessionTokensChange): void {
    for (const listener of tokenListeners) {
        try {
            listener(change)
        } catch {
            // A listener failure must not fail the sign in, refresh or sign out that changed the tokens.
        }
    }
}

function serializeStorage<T>(work: () => Promise<T>): Promise<T> {
    const result = storageQueue.then(work, work)
    storageQueue = result.then(
        () => undefined,
        () => undefined
    )
    return result
}

/**
 * Changes the in-memory session only and starts a new session generation. `key` names the slot that a refresh of
 * this session writes to.
 */
export function setSessionTokens(
    tokens: SessionTokens | null,
    owner: SessionIdentity | null = null,
    key: string | null = null
): void {
    identity = owner ? Object.freeze({ ...owner }) : null
    current = tokens
    activeKey = tokens ? key : null
    generation += 1
    publishTokens('session')
}

/** Drops the in-memory session and starts a new generation. The slots stay as they are. */
export function clearSession(): void {
    setSessionTokens(null)
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

function storedSession(tokens: SessionTokens, owner: SessionIdentity | null): string {
    if (!owner || owner.method !== tokens.kind) {
        throw new Error('Session identity is required to persist credentials')
    }
    return JSON.stringify({ version: 1, identity: owner, tokens } satisfies SessionEnvelope)
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

function parseEnvelope(raw: string): { identity: SessionIdentity; tokens: SessionTokens } | null {
    let parsed: unknown = null
    try {
        parsed = JSON.parse(raw)
    } catch {
        return null
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
    if (!validOwner || !tokens) {
        return null
    }
    return {
        identity: { host: owner.host, clientId: owner.clientId, method: owner.method, userUuid: owner.userUuid },
        tokens,
    }
}

type SlotRead = { kind: 'ok'; session: StoredSession } | { kind: 'absent' } | { kind: 'unreadable' }

/**
 * `absent` covers a missing item and one whose envelope names another account, so a slot never pairs its token with
 * another account's host. `unreadable` is a storage error, such as a keychain that is still locked, which must not
 * cost the user the account.
 */
async function readSlot(key: string): Promise<SlotRead> {
    let raw: string | null
    try {
        raw = await readItem(slotKey(key))
    } catch {
        return { kind: 'unreadable' }
    }
    const session = await slotSession(key, raw)
    return session ? { kind: 'ok', session } : { kind: 'absent' }
}

async function slotSession(key: string, raw: string | null): Promise<StoredSession | null> {
    const envelope = raw === null ? null : parseEnvelope(raw)
    if (!envelope) {
        return null
    }
    const owner = await accountKey(envelope.identity.host, envelope.identity.userUuid)
    return owner === key ? { key, ...envelope } : null
}

/** Null when the index is missing or malformed. Throws when storage fails, so a caller never rewrites it blind. */
async function readIndex(): Promise<AccountIndex | null> {
    const raw = await readItem(INDEX_KEY)
    if (raw === null) {
        return null
    }
    try {
        const parsed = JSON.parse(raw) as Partial<AccountIndex>
        if (
            parsed.version === 1 &&
            Array.isArray(parsed.keys) &&
            parsed.keys.every((key) => typeof key === 'string') &&
            (parsed.active === null || typeof parsed.active === 'string')
        ) {
            return { version: 1, active: parsed.active, keys: parsed.keys }
        }
    } catch {
        // A malformed index reads as missing.
    }
    return null
}

async function writeIndex(active: string | null, keys: readonly string[]): Promise<void> {
    await writeItem(INDEX_KEY, JSON.stringify({ version: 1, active, keys: [...new Set(keys)] } satisfies AccountIndex))
}

function sameIdentity(a: SessionIdentity, b: SessionIdentity): boolean {
    return a.host === b.host && a.userUuid === b.userUuid && a.method === b.method && a.clientId === b.clientId
}

async function migrateLegacySession(index: AccountIndex | null): Promise<AccountIndex | null> {
    let raw: string | null
    try {
        raw = await readItem(LEGACY_SESSION_KEY)
    } catch {
        return index
    }
    if (raw === null) {
        return index
    }
    const envelope = parseEnvelope(raw)
    if (envelope) {
        // Only an app version before multi-account writes this item, so a valid one is the latest sign-in. The slot
        // goes first, then the index that points to it, then the legacy item. A crash between the steps leaves the
        // legacy item for the next launch to move again, or a slot and index that already agree.
        const key = await accountKey(envelope.identity.host, envelope.identity.userUuid)
        await writeItem(slotKey(key), storedSession(envelope.tokens, envelope.identity))
        const keys = [...(index?.keys ?? []).filter((existing) => existing !== key), key]
        await writeIndex(key, keys)
        index = { version: 1, active: key, keys }
    }
    try {
        await deleteItem(LEGACY_SESSION_KEY)
    } catch {
        // The next launch moves it again, to the same slot.
    }
    return index
}

export interface LoadedAccounts {
    /** The account that was active at the last run. Null when none was, or when its slot is gone or unreadable. */
    active: StoredSession | null
    /** The identity of every readable slot, the active one too. */
    stored: { key: string; identity: SessionIdentity }[]
    /** Every account that still has a slot, readable or not. Null when the storage could not be read at all. */
    keys: string[] | null
}

/**
 * Restores the active account's session into memory and reports which accounts have a slot. It moves a session that
 * an earlier app version stored into its account's slot, and drops index entries whose slot is gone.
 */
export async function loadAccounts(): Promise<LoadedAccounts> {
    return serializeStorage(async () => {
        let loaded: LoadedAccounts = { active: null, stored: [], keys: null }
        try {
            const index = await migrateLegacySession(await readIndex())
            const sessions: StoredSession[] = []
            const kept: string[] = []
            for (const key of index?.keys ?? []) {
                const slot = await readSlot(key)
                if (slot.kind === 'ok') {
                    sessions.push(slot.session)
                }
                if (slot.kind !== 'absent') {
                    kept.push(key)
                }
            }
            const active = sessions.find((session) => session.key === index?.active) ?? null
            if (index && kept.length !== index.keys.length) {
                for (const key of index.keys.filter((key) => !kept.includes(key))) {
                    await deleteItem(slotKey(key)).catch(() => undefined)
                }
                await writeIndex(index.active !== null && kept.includes(index.active) ? index.active : null, kept)
            }
            loaded = {
                active,
                stored: sessions.map((session) => ({ key: session.key, identity: session.identity })),
                keys: kept,
            }
        } catch {
            // Storage failed. The launch continues signed out and leaves every item for the next launch.
        }
        const { active } = loaded
        setSessionTokens(active?.tokens ?? null, active?.identity ?? null, active?.key ?? null)
        return loaded
    })
}

/** Loads the active account's session into memory. */
export async function loadTokens(): Promise<SessionTokens | null> {
    return (await loadAccounts()).active?.tokens ?? null
}

/** One account's slot, or null when it is missing, unreadable or holds another account's session. */
export async function readAccountSession(key: string): Promise<StoredSession | null> {
    return serializeStorage(async () => {
        const slot = await readSlot(key)
        return slot.kind === 'ok' ? slot.session : null
    })
}

/**
 * Writes the slot of an account that has none in the index, before its session starts, so a storage failure leaves
 * the active session as it was. `undo` restores what the slot held before.
 */
export async function writeAccountSlot(
    key: string,
    tokens: SessionTokens,
    owner: SessionIdentity
): Promise<{ replaced: StoredSession | null; undo: () => Promise<void> }> {
    return serializeStorage(async () => {
        let raw: string | null = null
        try {
            raw = await readItem(slotKey(key))
        } catch {
            raw = null
        }
        const replaced = await slotSession(key, raw)
        await writeItem(slotKey(key), storedSession(tokens, owner))
        return {
            replaced,
            undo: () =>
                serializeStorage(async () => {
                    try {
                        await (raw === null ? deleteItem(slotKey(key)) : writeItem(slotKey(key), raw))
                    } catch {
                        // The slot is not in the index, so no launch reads it.
                    }
                }),
        }
    })
}

/**
 * Makes a stored account the active session: the index first, then memory and `publish` in the same turn, so the
 * store never shows one account while the client holds another account's token.
 */
export async function activateAccountSession(
    session: StoredSession,
    canPublish: () => boolean,
    publish: () => void
): Promise<boolean> {
    return serializeStorage(async () => {
        if (!canPublish()) {
            return false
        }
        const index = await readIndex()
        await writeIndex(session.key, [...(index?.keys ?? []), session.key])
        if (!canPublish()) {
            // A sign out or a later sign-in started while SecureStore was writing.
            await (index ? writeIndex(index.active, index.keys) : deleteItem(INDEX_KEY))
            return false
        }
        setSessionTokens(session.tokens, session.identity, session.key)
        publish()
        return true
    })
}

/** `session`: memory and slot hold the tokens. `stored`: only the slot does. `gone`: the account left the device. */
export type RefreshedTokensResult = 'session' | 'stored' | 'gone'

/**
 * Stores tokens that a refresh rotated. The server consumed the refresh token in the slot, so the new pair belongs in
 * the same account's slot even when the user switched away while the refresh was in flight. Memory takes the pair only
 * while it still holds session `generation` of that account. The slot must still hold `used`, the refresh token the
 * refresh sent, so a refresh never overwrites a newer sign-in or a removed account.
 */
export async function saveRefreshedTokens({
    key,
    owner,
    used,
    tokens,
    generation: expected,
}: {
    key: string
    owner: SessionIdentity
    used: string
    tokens: SessionTokens
    generation: number | null
}): Promise<RefreshedTokensResult> {
    const isSession = (): boolean => generation === expected && activeKey === key && current?.refreshToken === used
    return serializeStorage(async () => {
        if (!isSession()) {
            const slot = await readSlot(key)
            if (
                slot.kind !== 'ok' ||
                !sameIdentity(slot.session.identity, owner) ||
                slot.session.tokens.refreshToken !== used
            ) {
                return 'gone'
            }
        }
        await writeItem(slotKey(key), storedSession(tokens, owner))
        if (!isSession()) {
            return 'stored'
        }
        current = tokens
        publishTokens('refresh')
        return 'session'
    })
}

/**
 * Deletes an account's slot, then its index entry, so a failure between the two leaves an entry that the next launch
 * drops instead of a slot that no index lists. Memory stays as it is.
 */
export async function forgetAccountSlot(key: string): Promise<void> {
    await serializeStorage(async () => {
        try {
            await deleteItem(slotKey(key))
            const index = await readIndex()
            if (index) {
                await writeIndex(
                    index.active === key ? null : index.active,
                    index.keys.filter((existing) => existing !== key)
                )
            }
        } catch {
            // A slot left behind holds a revoked or expired token, which the server rejects.
        }
    })
}

/**
 * Persists tokens as the active account's session without a new generation, for a session that `setSessionTokens`
 * started.
 */
export async function saveTokens(tokens: SessionTokens, owner: SessionIdentity | null = identity): Promise<void> {
    if (!owner) {
        throw new Error('Session identity is required to persist credentials')
    }
    const key = await accountKey(owner.host, owner.userUuid)
    await serializeStorage(async () => {
        await writeItem(slotKey(key), storedSession(tokens, owner))
        const index = await readIndex()
        await writeIndex(key, [...(index?.keys ?? []), key])
        current = tokens
        identity = Object.freeze({ ...owner })
        activeKey = key
        publishTokens('refresh')
    })
}
