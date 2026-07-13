import { randomUUID } from 'node:crypto'

import type { RedisLike } from './RedisCache'
import { SharedBlobCache, type SharedBlobCacheOptions } from './SharedBlobCache'

export const DEFAULT_SKILL_ARCHIVE_URL =
    'https://github.com/PostHog/posthog/releases/download/agent-skills-latest/skills.zip'

const MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
const ARCHIVE_DOWNLOAD_TIMEOUT_MS = 15_000
const NAMESPACE = 'product-skills'

export type SkillArchiveCacheResult = 'fresh_hit' | 'stale_hit' | 'cold_refresh' | 'waited' | 'fallback'

export interface SkillArchiveLoadResult {
    bytes: Uint8Array
    result: SkillArchiveCacheResult
}

export interface SkillArchiveCacheOptions extends SharedBlobCacheOptions {
    archiveUrl?: string
    fetchArchive?: (url: string) => Promise<Uint8Array>
}

/** Redis-backed stale-while-revalidate cache for the published skills.zip. */
export class SkillArchiveCache extends SharedBlobCache {
    private readonly archiveUrl: string
    private readonly fetchArchive: (url: string) => Promise<Uint8Array>

    constructor(redis: RedisLike, opts: SkillArchiveCacheOptions = {}) {
        super(redis, NAMESPACE, opts)
        this.archiveUrl = opts.archiveUrl ?? DEFAULT_SKILL_ARCHIVE_URL
        this.fetchArchive = opts.fetchArchive ?? downloadArchive
    }

    async loadOrRefresh(): Promise<SkillArchiveLoadResult> {
        const cached = await this.readCache()
        if (cached?.fresh) {
            return { bytes: cached.bytes, result: 'fresh_hit' }
        }
        if (cached) {
            void this.refreshInBackground()
            return { bytes: cached.bytes, result: 'stale_hit' }
        }

        const token = randomUUID()
        if (await this.acquireLock(token)) {
            try {
                const bytes = await this.loadArchive()
                await this.writeCache(bytes)
                return { bytes, result: 'cold_refresh' }
            } finally {
                await this.releaseLock(token)
            }
        }

        const waited = await this.waitForCache()
        if (waited) {
            return { bytes: waited, result: 'waited' }
        }
        return { bytes: await this.loadArchive(), result: 'fallback' }
    }

    private async refreshInBackground(): Promise<void> {
        const token = randomUUID()
        if (!(await this.acquireLock(token))) {
            return
        }
        try {
            const bytes = await this.loadArchive()
            await this.writeCache(bytes)
        } catch (error) {
            console.error('[SkillArchiveCache] background refresh failed:', error)
        } finally {
            await this.releaseLock(token)
        }
    }

    private async loadArchive(): Promise<Uint8Array> {
        const bytes = await this.fetchArchive(this.archiveUrl)
        if (bytes.length === 0 || bytes.length > MAX_ARCHIVE_BYTES) {
            throw new Error(`Invalid skill archive size: ${bytes.length} bytes`)
        }
        return bytes
    }
}

async function downloadArchive(url: string): Promise<Uint8Array> {
    const response = await fetch(url, { signal: AbortSignal.timeout(ARCHIVE_DOWNLOAD_TIMEOUT_MS) })
    if (!response.ok) {
        throw new Error(`Failed to download skill archive: HTTP ${response.status}`)
    }
    const contentLength = Number(response.headers.get('content-length'))
    if (Number.isFinite(contentLength) && contentLength > MAX_ARCHIVE_BYTES) {
        throw new Error(`Skill archive is too large: ${contentLength} bytes`)
    }
    return new Uint8Array(await response.arrayBuffer())
}
