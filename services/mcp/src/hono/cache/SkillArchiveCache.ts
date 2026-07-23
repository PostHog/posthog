import { createHash, randomUUID } from 'node:crypto'

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

/**
 * Outcome of a (possibly conditional) archive download. `not_modified` is the
 * 304 sentinel returned when we sent `If-None-Match` and the asset is unchanged.
 */
export type SkillArchiveFetchResult =
    | { status: 'downloaded'; bytes: Uint8Array; etag?: string }
    | { status: 'not_modified' }

export interface SkillArchiveCacheOptions extends SharedBlobCacheOptions {
    archiveUrl?: string
    fetchArchive?: (url: string, etag?: string) => Promise<SkillArchiveFetchResult>
}

/** Redis-backed stale-while-revalidate cache for the published skills.zip. */
export class SkillArchiveCache extends SharedBlobCache {
    private readonly archiveUrl: string
    private readonly fetchArchive: (url: string, etag?: string) => Promise<SkillArchiveFetchResult>

    constructor(redis: RedisLike, opts: SkillArchiveCacheOptions = {}) {
        const archiveUrl = opts.archiveUrl ?? DEFAULT_SKILL_ARCHIVE_URL
        const namespace =
            archiveUrl === DEFAULT_SKILL_ARCHIVE_URL
                ? NAMESPACE
                : `${NAMESPACE}:${createHash('sha256').update(archiveUrl).digest('hex').slice(0, 16)}`
        super(redis, namespace, opts)
        this.archiveUrl = archiveUrl
        this.fetchArchive = opts.fetchArchive ?? downloadArchive
    }

    async loadOrRefresh(): Promise<SkillArchiveLoadResult> {
        const cached = await this.readCache()
        if (cached?.fresh) {
            return { bytes: cached.bytes, result: 'fresh_hit' }
        }
        if (cached) {
            void this.refreshInBackground(cached.etag)
            return { bytes: cached.bytes, result: 'stale_hit' }
        }

        const token = randomUUID()
        if (await this.acquireLock(token)) {
            try {
                const { bytes, etag } = await this.downloadFull()
                await this.writeCache(bytes, etag)
                return { bytes, result: 'cold_refresh' }
            } finally {
                await this.releaseLock(token)
            }
        }

        const waited = await this.waitForCache()
        if (waited) {
            return { bytes: waited, result: 'waited' }
        }
        return { bytes: (await this.downloadFull()).bytes, result: 'fallback' }
    }

    private async refreshInBackground(etag?: string): Promise<void> {
        const token = randomUUID()
        if (!(await this.acquireLock(token))) {
            return
        }
        try {
            const result = await this.fetchArchiveChecked(etag)
            if (result.status === 'not_modified') {
                // Archive unchanged since we cached it: bump freshness and re-extend
                // the hard TTLs in place, skipping the re-download and re-parse.
                await this.touchCache()
            } else {
                await this.writeCache(result.bytes, result.etag)
            }
        } catch (error) {
            console.error('[SkillArchiveCache] background refresh failed:', error)
        } finally {
            await this.releaseLock(token)
        }
    }

    /** Fetch a full archive body. Callers without cached bytes never revalidate. */
    private async downloadFull(): Promise<{ bytes: Uint8Array; etag?: string }> {
        const result = await this.fetchArchiveChecked()
        if (result.status === 'not_modified') {
            // Only reachable if the server 304s without an If-None-Match request.
            throw new Error('Skill archive server returned 304 Not Modified without a conditional request')
        }
        return { bytes: result.bytes, etag: result.etag }
    }

    private async fetchArchiveChecked(etag?: string): Promise<SkillArchiveFetchResult> {
        const result = await this.fetchArchive(this.archiveUrl, etag)
        if (result.status === 'downloaded' && (result.bytes.length === 0 || result.bytes.length > MAX_ARCHIVE_BYTES)) {
            throw new Error(`Invalid skill archive size: ${result.bytes.length} bytes`)
        }
        return result
    }
}

async function downloadArchive(url: string, etag?: string): Promise<SkillArchiveFetchResult> {
    const headers: Record<string, string> = {}
    if (etag) {
        headers['If-None-Match'] = etag
    }
    const response = await fetch(url, { headers, signal: AbortSignal.timeout(ARCHIVE_DOWNLOAD_TIMEOUT_MS) })
    if (response.status === 304) {
        return { status: 'not_modified' }
    }
    if (!response.ok) {
        throw new Error(`Failed to download skill archive: HTTP ${response.status}`)
    }
    const contentLength = Number(response.headers.get('content-length'))
    if (Number.isFinite(contentLength) && contentLength > MAX_ARCHIVE_BYTES) {
        throw new Error(`Skill archive is too large: ${contentLength} bytes`)
    }
    const bytes = new Uint8Array(await response.arrayBuffer())
    // `response.headers` is the final response after redirects (GitHub release
    // assets 302 to objects.githubusercontent.com), so this is the asset's own
    // validator. Absent → we store no etag and behave exactly as before.
    const validator = response.headers.get('etag') ?? undefined
    return { status: 'downloaded', bytes, etag: validator }
}
