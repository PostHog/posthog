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

type SlotContent =
    | { kind: 'ok'; session: StoredSession }
    | { kind: 'absent' }
    | { kind: 'foreign' }
    | { kind: 'unreadable' }

/**
 * `missing`: no slot, or a slot whose envelope names another account, so a slot never pairs its token with another
 * account's host. `unreadable`: storage failed, or the envelope has a shape this version cannot parse, such as one a
 * later app version wrote. An unreadable slot must not cost the user the account.
 */
export type AccountSlotRead = { kind: 'ok'; session: StoredSession } | { kind: 'missing' } | { kind: 'unreadable' }

/**
 * A rotated pair that its slot could not take because SecureStore failed. The server consumed `expect`, the refresh
 * token the slot still holds, and a replay of it later revokes the whole token family, so the pair stays here until a
 * read of the slot writes it.
 */
interface HeldPair {
    owner: SessionIdentity
    expect: string
    tokens: SessionTokens
}

const heldPairs = new Map<string, HeldPair>()

async function slotContent(key: string, raw: string | null): Promise<SlotContent> {
    if (raw === null) {
        return { kind: 'absent' }
    }
    const envelope = parseEnvelope(raw)
    if (!envelope) {
        return { kind: 'unreadable' }
    }
    const owner = await accountKey(envelope.identity.host, envelope.identity.userUuid)
    return owner === key ? { kind: 'ok', session: { key, ...envelope } } : { kind: 'foreign' }
}

async function withHeldPair(key: string, slot: SlotContent): Promise<SlotContent> {
    const held = heldPairs.get(key)
    if (!held || slot.kind === 'unreadable') {
        return slot
    }
    if (
        slot.kind !== 'ok' ||
        !sameIdentity(slot.session.identity, held.owner) ||
        slot.session.tokens.refreshToken !== held.expect
    ) {
        heldPairs.delete(key)
        return slot
    }
    try {
        await writeItem(slotKey(key), storedSession(held.tokens, held.owner))
        heldPairs.delete(key)
    } catch {
        // Still held for the next read.
    }
    return { kind: 'ok', session: { ...slot.session, tokens: held.tokens } }
}

async function readSlot(key: string): Promise<SlotContent> {
    let raw: string | null
    try {
        raw = await readItem(slotKey(key))
    } catch {
        return { kind: 'unreadable' }
    }
    return withHeldPair(key, await slotContent(key, raw))
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

async function migrateLegacySession(
    index: AccountIndex | null
): Promise<{ index: AccountIndex | null; read: boolean }> {
    let raw: string | null
    try {
        raw = await readItem(LEGACY_SESSION_KEY)
    } catch {
        return { index, read: false }
    }
    if (raw === null) {
        return { index, read: true }
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
    return { index, read: true }
}

export interface LoadedAccounts {
    /** The account that was active at the last run. Null when none was, or when its slot is gone or unreadable. */
    active: StoredSession | null
    stored: { key: string; identity: SessionIdentity }[]
    /** Every account that still has a slot, readable or not. Null when the index could not be read. */
    keys: string[] | null
    unreadable: string[]
    /** False when a storage failure can hide the session: the index, the legacy item or the active slot did not read. */
    complete: boolean
}

/**
 * Restores the active account's session into memory and reports which accounts have a slot. It moves a session that
 * an earlier app version stored into its account's slot, and drops index entries whose slot is gone.
 */
export async function loadAccounts(): Promise<LoadedAccounts> {
    return serializeStorage(async () => {
        let loaded: LoadedAccounts = { active: null, stored: [], keys: null, unreadable: [], complete: false }
        try {
            const { index, read: legacyRead } = await migrateLegacySession(await readIndex())
            const sessions: StoredSession[] = []
            const kept: string[] = []
            const unreadable: string[] = []
            const foreign: string[] = []
            for (const key of index?.keys ?? []) {
                const slot = await readSlot(key)
                if (slot.kind === 'ok') {
                    sessions.push(slot.session)
                } else if (slot.kind === 'unreadable') {
                    unreadable.push(key)
                } else if (slot.kind === 'foreign') {
                    foreign.push(key)
                }
                if (slot.kind === 'ok' || slot.kind === 'unreadable') {
                    kept.push(key)
                }
            }
            const active = sessions.find((session) => session.key === index?.active) ?? null
            if (index && kept.length !== index.keys.length) {
                // A slot that fails to parse stays, because a later app version may have written it. Only a verified
                // owner mismatch is deleted.
                for (const key of foreign) {
                    await deleteItem(slotKey(key)).catch(() => undefined)
                }
                await writeIndex(
                    index.active !== null && kept.includes(index.active) ? index.active : null,
                    kept
                ).catch(() => undefined)
            }
            loaded = {
                active,
                stored: sessions.map((session) => ({ key: session.key, identity: session.identity })),
                keys: kept,
                unreadable,
                complete: legacyRead && !(index?.active && unreadable.includes(index.active)),
            }
        } catch {
            // The launch continues signed out and leaves every item for a later restore.
        }
        const { active } = loaded
        setSessionTokens(active?.tokens ?? null, active?.identity ?? null, active?.key ?? null)
        return loaded
    })
}

export async function loadTokens(): Promise<SessionTokens | null> {
    return (await loadAccounts()).active?.tokens ?? null
}

export async function readAccountSession(key: string): Promise<AccountSlotRead> {
    return serializeStorage(async () => {
        const slot = await readSlot(key)
        return slot.kind === 'ok' || slot.kind === 'unreadable' ? slot : { kind: 'missing' }
    })
}

export interface WrittenSlot {
    /** What the slot held, when it could be read. Its refresh token is the caller's to revoke. */
    replaced: StoredSession | null
    /** `kept`: what the slot held could not be read or put back, so the slot keeps the new tokens. */
    undo: () => Promise<'restored' | 'kept'>
}

/**
 * Writes an account's slot before its session starts, so a storage failure leaves the active session as it was. A slot
 * that cannot be read is still replaced, because a keystore that cannot decrypt an item can often write a new one.
 */
export async function writeAccountSlot(
    key: string,
    tokens: SessionTokens,
    owner: SessionIdentity
): Promise<WrittenSlot> {
    return serializeStorage(async () => {
        let raw: string | null = null
        let rawRead = true
        try {
            raw = await readItem(slotKey(key))
        } catch {
            rawRead = false
        }
        const before = rawRead ? await withHeldPair(key, await slotContent(key, raw)) : null
        heldPairs.delete(key)
        await writeItem(slotKey(key), storedSession(tokens, owner))
        return {
            replaced: before?.kind === 'ok' ? before.session : null,
            undo: () =>
                serializeStorage(async () => {
                    if (!rawRead) {
                        return 'kept'
                    }
                    try {
                        if (before?.kind === 'ok') {
                            await writeItem(slotKey(key), storedSession(before.session.tokens, before.session.identity))
                        } else if (raw === null) {
                            await deleteItem(slotKey(key))
                        } else {
                            await writeItem(slotKey(key), raw)
                        }
                        return 'restored'
                    } catch {
                        return 'kept'
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

/**
 * `session`: memory took the pair. `stored`: only the slot did. `held`: neither memory nor the slot did, and the pair
 * waits for the slot's next read. `gone`: the account left the device or signed in again.
 */
export type RefreshedTokensResult = 'session' | 'stored' | 'held' | 'gone'

/**
 * Stores tokens that a refresh rotated. The server consumed `used`, so the pair belongs in the same account's slot even
 * when the user switched away. Memory takes it whenever it still holds `used` for that slot, whatever its generation,
 * because memory would otherwise replay the consumed token later. The slot must still hold `used`, so a refresh never
 * overwrites a newer sign-in or a removed account.
 */
export async function saveRefreshedTokens({
    key,
    owner,
    used,
    tokens,
}: {
    key: string
    owner: SessionIdentity
    used: string
    tokens: SessionTokens
}): Promise<RefreshedTokensResult> {
    return serializeStorage(async () => {
        const slot = await readSlot(key)
        const held = heldPairs.get(key)
        if (slot.kind === 'absent' || slot.kind === 'foreign') {
            return 'gone'
        }
        if (slot.kind === 'unreadable' && held && held.tokens.refreshToken !== used) {
            return 'gone'
        }
        if (
            slot.kind === 'ok' &&
            (!sameIdentity(slot.session.identity, owner) || slot.session.tokens.refreshToken !== used)
        ) {
            return 'gone'
        }
        let written = false
        if (slot.kind === 'ok') {
            try {
                await writeItem(slotKey(key), storedSession(tokens, owner))
                heldPairs.delete(key)
                written = true
            } catch {
                written = false
            }
        }
        if (!written) {
            heldPairs.set(key, { owner, expect: heldPairs.get(key)?.expect ?? used, tokens })
        }
        if (activeKey === key && current?.refreshToken === used) {
            current = tokens
            publishTokens('refresh')
            return 'session'
        }
        return written ? 'stored' : 'held'
    })
}

/**
 * Deletes an account's slot, then its index entry, so a failure between the two leaves an entry that the next launch
 * drops instead of a slot that no index lists. Memory stays as it is. Resolves false when storage failed.
 */
export async function forgetAccountSlot(key: string): Promise<boolean> {
    return serializeStorage(async () => {
        heldPairs.delete(key)
        try {
            await deleteItem(slotKey(key))
            const index = await readIndex()
            if (index) {
                await writeIndex(
                    index.active === key ? null : index.active,
                    index.keys.filter((existing) => existing !== key)
                )
            }
            return true
        } catch {
            return false
        }
    })
}
