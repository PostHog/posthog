/**
 * File-backed store that stands in for Redis behind the nonce ledger and
 * the payload stash.
 *
 * The CLI runs one process per command, so a prepare and its execute are
 * two different processes. An in-memory stash would always look empty to
 * execute. One small file per key keeps the confirmation alive between the
 * two commands, and `unlink` gives the stash `take()` the same exclusive
 * burn that Redis `DEL` does.
 *
 * Only the Redis semantics the ledger and the stash use are implemented:
 * expiring keys, set-if-absent, and a counter. The caller creates
 * `directory` before the first operation.
 */

import { createHash } from 'node:crypto'
import * as fs from 'node:fs/promises'
import * as path from 'node:path'

import type { NonceLedgerRedis } from './nonce-ledger'
import type { PayloadStashRedis } from './payload-stash'

interface Entry {
    value: string
    expiresAtMs: number | null
}

function hasCode(error: unknown, code: string): boolean {
    return typeof error === 'object' && error !== null && (error as { code?: unknown }).code === code
}

function parseSetArgs(args: (string | number)[]): { ttlSeconds: number | null; nx: boolean } {
    let ttlSeconds: number | null = null
    let nx = false
    for (let index = 0; index < args.length; index += 1) {
        const arg = args[index]
        if (typeof arg !== 'string') {
            continue
        }
        const flag = arg.toUpperCase()
        if (flag === 'NX') {
            nx = true
        } else if (flag === 'EX') {
            ttlSeconds = Number(args[index + 1])
        }
    }
    return { ttlSeconds, nx }
}

export class FileKeyValueStore implements NonceLedgerRedis, PayloadStashRedis {
    private pruned = false

    constructor(private readonly directory: string) {}

    async set(key: string, value: string, ...args: (string | number)[]): Promise<string | null> {
        const { ttlSeconds, nx } = parseSetArgs(args)
        const file = this.pathFor(key)
        const entry = this.serialize(value, ttlSeconds)
        await this.pruneExpired()

        if (nx) {
            try {
                await fs.writeFile(file, entry, { flag: 'wx', mode: 0o600 })
                return 'OK'
            } catch (error) {
                if (!hasCode(error, 'EEXIST')) {
                    throw error
                }
            }
            // An expired key is absent as far as Redis is concerned, and
            // `read` removes it, so the write below can take its place.
            if ((await this.read(file)) !== null) {
                return null
            }
        }

        await fs.writeFile(file, entry, { mode: 0o600 })
        return 'OK'
    }

    async get(key: string): Promise<string | null> {
        const entry = await this.read(this.pathFor(key))
        return entry === null ? null : entry.value
    }

    async del(...keys: string[]): Promise<number> {
        let deleted = 0
        for (const key of keys) {
            try {
                await fs.unlink(this.pathFor(key))
                deleted += 1
            } catch (error) {
                if (!hasCode(error, 'ENOENT')) {
                    throw error
                }
            }
        }
        return deleted
    }

    async incrby(key: string, increment: number): Promise<number> {
        const file = this.pathFor(key)
        const entry = await this.read(file)
        const total = (entry === null ? 0 : Number.parseInt(entry.value, 10) || 0) + increment
        const expiresAtMs = entry?.expiresAtMs ?? null
        await fs.writeFile(file, JSON.stringify({ value: String(total), expiresAtMs }), { mode: 0o600 })
        return total
    }

    async expire(key: string, seconds: number): Promise<number> {
        const file = this.pathFor(key)
        const entry = await this.read(file)
        if (entry === null) {
            return 0
        }
        await fs.writeFile(file, this.serialize(entry.value, seconds), { mode: 0o600 })
        return 1
    }

    async ttl(key: string): Promise<number> {
        const entry = await this.read(this.pathFor(key))
        if (entry === null) {
            return -2
        }
        if (entry.expiresAtMs === null) {
            return -1
        }
        return Math.max(0, Math.ceil((entry.expiresAtMs - Date.now()) / 1000))
    }

    /** Hashed so a key with separators or user data never shapes a path. */
    private pathFor(key: string): string {
        return path.join(this.directory, `${createHash('sha256').update(key).digest('hex').slice(0, 32)}.json`)
    }

    private serialize(value: string, ttlSeconds: number | null): string {
        const expiresAtMs = ttlSeconds === null ? null : Date.now() + ttlSeconds * 1000
        return JSON.stringify({ value, expiresAtMs })
    }

    private async read(file: string): Promise<Entry | null> {
        let raw: string
        try {
            raw = await fs.readFile(file, 'utf-8')
        } catch (error) {
            if (hasCode(error, 'ENOENT')) {
                return null
            }
            throw error
        }

        let parsed: Partial<Entry> | null = null
        try {
            parsed = JSON.parse(raw) as Partial<Entry>
        } catch {
            parsed = null
        }
        if (parsed === null || typeof parsed.value !== 'string') {
            await this.unlinkQuietly(file)
            return null
        }
        const expiresAtMs = typeof parsed.expiresAtMs === 'number' ? parsed.expiresAtMs : null
        if (expiresAtMs !== null && expiresAtMs <= Date.now()) {
            await this.unlinkQuietly(file)
            return null
        }
        return { value: parsed.value, expiresAtMs }
    }

    /**
     * Drop entries whose TTL has passed, once per store. Nothing else ever
     * revisits a confirmation the user abandoned, so without this the
     * directory keeps one file per prepare that never reached its execute.
     */
    private async pruneExpired(): Promise<void> {
        if (this.pruned) {
            return
        }
        this.pruned = true
        let names: string[]
        try {
            names = await fs.readdir(this.directory)
        } catch {
            return
        }
        for (const name of names) {
            await this.read(path.join(this.directory, name))
        }
    }

    private async unlinkQuietly(file: string): Promise<void> {
        try {
            await fs.unlink(file)
        } catch {
            // Already gone, or another process won the race — either is fine.
        }
    }
}
