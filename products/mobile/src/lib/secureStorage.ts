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

async function manifest(key: string): Promise<Manifest | null> {
    try {
        const value: unknown = JSON.parse((await itemStorage.getItem(key)) ?? 'null')
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
    } catch {}
    return null
}

async function removeChunks(key: string, saved: Manifest | null): Promise<void> {
    if (saved) {
        await Promise.all(
            Array.from({ length: saved.count }, (_, index) =>
                itemStorage.removeItem(`${key}.${saved.revision}.${index}`)
            )
        )
    }
}

// Each chunk stays below SecureStore's 2 KiB limit even for non-ASCII text. The manifest switches only after all
// chunks are saved, so an interrupted write leaves the previous complete value readable.
export const secureStorage: StringStorage = {
    getItem: async (key) => {
        const saved = await manifest(key)
        if (!saved) {
            return null
        }
        const parts = await Promise.all(
            Array.from({ length: saved.count }, (_, index) => itemStorage.getItem(`${key}.${saved.revision}.${index}`))
        )
        return parts.every((part) => part !== null) ? parts.join('') : null
    },
    setItem: async (key, value) => {
        const previous = await manifest(key)
        const revision = Crypto.randomUUID()
        const characters = Array.from(value)
        const parts: string[] = []
        for (let index = 0; index < characters.length; index += 500) {
            parts.push(characters.slice(index, index + 500).join(''))
        }
        if (!parts.length) {
            parts.push('')
        }
        const next = { revision, count: parts.length }
        try {
            await Promise.all(parts.map((part, index) => itemStorage.setItem(`${key}.${revision}.${index}`, part)))
            await itemStorage.setItem(key, JSON.stringify(next))
        } catch (error) {
            await removeChunks(key, next).catch(() => undefined)
            throw error
        }
        await removeChunks(key, previous)
    },
    removeItem: async (key) => {
        const previous = await manifest(key)
        await itemStorage.removeItem(key)
        await removeChunks(key, previous)
    },
}
