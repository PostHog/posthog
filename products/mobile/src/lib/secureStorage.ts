import * as Crypto from 'expo-crypto'
import * as SecureStore from 'expo-secure-store'
import { Platform } from 'react-native'

export interface StringStorage {
    getItem: (key: string) => Promise<string | null>
    setItem: (key: string, value: string) => Promise<void>
    removeItem: (key: string) => Promise<void>
}

const webMemory = new Map<string, string>()
const itemStorage: StringStorage = {
    getItem: (key) =>
        Platform.OS === 'web' ? Promise.resolve(webMemory.get(key) ?? null) : SecureStore.getItemAsync(key),
    setItem: async (key, value) => {
        if (Platform.OS === 'web') {
            webMemory.set(key, value)
        } else {
            await SecureStore.setItemAsync(key, value)
        }
    },
    removeItem: async (key) => {
        if (Platform.OS === 'web') {
            webMemory.delete(key)
        } else {
            await SecureStore.deleteItemAsync(key)
        }
    },
}

interface Manifest {
    revision: string
    count: number
}

function asManifest(value: unknown): Manifest | null {
    if (value && typeof value === 'object') {
        const record = value as Record<string, unknown>
        if (
            typeof record.revision === 'string' &&
            typeof record.count === 'number' &&
            Number.isSafeInteger(record.count) &&
            record.count > 0 &&
            record.count <= 10000
        ) {
            return { revision: record.revision, count: record.count }
        }
    }
    return null
}

async function storedJson(key: string): Promise<unknown> {
    const raw = await itemStorage.getItem(key)
    try {
        return JSON.parse(raw ?? 'null')
    } catch {
        return null
    }
}

async function revisions(key: string): Promise<Manifest[]> {
    const value = await storedJson(`${key}.revisions`)
    return Array.isArray(value) ? value.map(asManifest).filter((entry): entry is Manifest => entry !== null) : []
}

async function complete(work: Promise<void>[]): Promise<void> {
    // Settle every native operation before cleanup can remove partially written chunks.
    const results = await Promise.allSettled(work)
    const failed = results.find((result) => result.status === 'rejected')
    if (failed?.status === 'rejected') throw failed.reason
}

async function removeChunks(key: string, saved: Manifest | null): Promise<void> {
    if (saved) {
        await complete(
            Array.from({ length: saved.count }, (_, index) =>
                itemStorage.removeItem(`${key}.${saved.revision}.${index}`)
            )
        )
    }
}

async function recover(key: string): Promise<Manifest | null> {
    const saved = asManifest(await storedJson(key))
    const journal = await revisions(key)
    for (const entry of journal) {
        if (entry.revision !== saved?.revision) await removeChunks(key, entry)
    }
    if (journal.length) await itemStorage.removeItem(`${key}.revisions`)
    return saved
}

const operations = new Map<string, Promise<unknown>>()

function serialized<T>(key: string, work: () => Promise<T>): Promise<T> {
    const result = (operations.get(key) ?? Promise.resolve()).then(work)
    const settled = result.catch(() => undefined)
    operations.set(key, settled)
    void settled.then(() => {
        if (operations.get(key) === settled) operations.delete(key)
    })
    return result
}

// Each chunk stays below SecureStore's 2 KiB limit even for non-ASCII text. The journal retains
// unfinished revisions across restarts, while the manifest points to the last complete value.
export const secureStorage: StringStorage = {
    getItem: (key) =>
        serialized(key, async () => {
            const saved = await recover(key)
            if (!saved) return null
            const parts = await Promise.all(
                Array.from({ length: saved.count }, (_, index) =>
                    itemStorage.getItem(`${key}.${saved.revision}.${index}`)
                )
            )
            if (parts.some((part) => part === null)) throw new Error('Incomplete secure storage value')
            return parts.join('')
        }),
    setItem: (key, value) =>
        serialized(key, async () => {
            const previous = await recover(key)
            const revision = Crypto.randomUUID()
            const characters = Array.from(value)
            const parts: string[] = []
            for (let index = 0; index < characters.length; index += 500) {
                parts.push(characters.slice(index, index + 500).join(''))
            }
            if (!parts.length) parts.push('')
            const next = { revision, count: parts.length }
            await itemStorage.setItem(`${key}.revisions`, JSON.stringify(previous ? [previous, next] : [next]))
            try {
                await complete(parts.map((part, index) => itemStorage.setItem(`${key}.${revision}.${index}`, part)))
                await itemStorage.setItem(key, JSON.stringify(next))
            } catch (error) {
                await recover(key).catch(() => undefined)
                throw error
            }
            await recover(key)
        }),
    removeItem: (key) =>
        serialized(key, async () => {
            const previous = asManifest(await storedJson(key))
            const journal = await revisions(key)
            if (previous && !journal.some((entry) => entry.revision === previous.revision)) journal.push(previous)
            if (journal.length) await itemStorage.setItem(`${key}.revisions`, JSON.stringify(journal))
            await itemStorage.removeItem(key)
            for (const entry of journal) await removeChunks(key, entry)
            if (journal.length) await itemStorage.removeItem(`${key}.revisions`)
        }),
}
