/**
 * File-backed `PlanStore` for the CLI local execution mode (spec §4.8): the
 * CLI is one-shot per invocation, so plans must survive process exit. One JSON
 * record per plan under a private directory; `consume` rewrites the record as
 * a tombstone so reuse and expiry are rejected identically to the hosted path.
 *
 * The storage key (`<sub>:<phrase>`) is arbitrary user-influenced input (a
 * distinct_id can contain `/`, `..`, unicode), so it is never interpolated
 * into a path: the filename is the truncated SHA-256 of the key — pure hex the
 * key author never controls — and the plaintext key is stored inside the
 * record and verified on read, which also kills truncated-hash collisions.
 */

import { promises as fs } from 'node:fs'
import path from 'node:path'

import { sha256Hex } from './hashes'
import type { PlanStore, StoredPlan } from './plan-store'

interface PlanFileRecord {
    /** Plaintext storage key, verified on read (see module doc). */
    key: string
    /** Epoch ms; checked on every read, expired files are deleted lazily. */
    expiresAt: number
    /** `null` marks a consumed tombstone kept until `expiresAt`. */
    storedPlan: StoredPlan | null
}

export interface FilePlanStoreOptions {
    /** Directory holding one JSON record per plan; created on first write. */
    directory: string
    /** Injectable clock (ms) for deterministic expiry in tests. */
    now?: () => number
}

export class FilePlanStore implements PlanStore {
    private readonly directory: string
    private readonly now: () => number

    constructor(options: FilePlanStoreOptions) {
        this.directory = options.directory
        this.now = options.now ?? (() => Date.now())
    }

    async put(key: string, value: StoredPlan, ttlSeconds: number): Promise<void> {
        // Plan records carry scripts and the user's identity — keep the
        // directory and files private to the user (advisory on Windows).
        await fs.mkdir(this.directory, { recursive: true, mode: 0o700 })
        await this.deleteExpiredRecords()
        const record: PlanFileRecord = {
            key,
            expiresAt: this.now() + Math.max(1, ttlSeconds) * 1000,
            storedPlan: value,
        }
        await this.writeRecord(key, record)
    }

    async get(key: string): Promise<StoredPlan | null> {
        const record = await this.readRecord(key)
        // A tombstone reads as absent, so put's collision check treats consumed keys as free.
        return record?.storedPlan ?? null
    }

    async consume(key: string): Promise<StoredPlan | 'consumed' | null> {
        const record = await this.readRecord(key)
        if (!record) {
            return null
        }
        if (record.storedPlan === null) {
            return 'consumed'
        }
        // Tombstone keeps the original expiry so reuse gets a distinct message until the TTL runs out.
        await this.writeRecord(key, { ...record, storedPlan: null })
        return record.storedPlan
    }

    private filePath(key: string): string {
        return path.join(this.directory, `${sha256Hex(key).slice(0, 32)}.json`)
    }

    private async writeRecord(key: string, record: PlanFileRecord): Promise<void> {
        await fs.writeFile(this.filePath(key), JSON.stringify(record), { mode: 0o600 })
    }

    /** Read + validate the record for `key`; expired or corrupt files are deleted, mismatched keys ignored. */
    private async readRecord(key: string): Promise<PlanFileRecord | null> {
        const filePath = this.filePath(key)
        let raw: string
        try {
            raw = await fs.readFile(filePath, 'utf8')
        } catch {
            return null
        }
        let record: PlanFileRecord
        try {
            record = JSON.parse(raw) as PlanFileRecord
        } catch {
            await this.unlinkQuietly(filePath)
            return null
        }
        if (record.key !== key) {
            // Truncated-hash collision: the file belongs to another key — leave it alone.
            return null
        }
        if (this.now() >= record.expiresAt) {
            await this.unlinkQuietly(filePath)
            return null
        }
        return record
    }

    /** Opportunistic GC (on `put`, so reads stay one file): drop every expired sibling record. */
    private async deleteExpiredRecords(): Promise<void> {
        let entries: string[]
        try {
            entries = await fs.readdir(this.directory)
        } catch {
            return
        }
        const now = this.now()
        for (const entry of entries) {
            if (!entry.endsWith('.json')) {
                continue
            }
            const filePath = path.join(this.directory, entry)
            try {
                const record = JSON.parse(await fs.readFile(filePath, 'utf8')) as PlanFileRecord
                if (typeof record.expiresAt !== 'number' || now >= record.expiresAt) {
                    await this.unlinkQuietly(filePath)
                }
            } catch {
                // Unreadable/corrupt sibling: best-effort GC only, never fail the put.
            }
        }
    }

    private async unlinkQuietly(filePath: string): Promise<void> {
        try {
            await fs.unlink(filePath)
        } catch {}
    }
}
