import { createHash, randomUUID } from 'node:crypto'

import type { RedisLike } from './RedisCache'
import { hashBytes, SharedBlobCache, type SharedBlobCacheOptions, type SharedBlobVersion } from './SharedBlobCache'

export const DEFAULT_SKILL_ARCHIVE_URL =
    'https://github.com/PostHog/posthog/releases/download/agent-skills-latest/skills.zip'

const MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
const ARCHIVE_DOWNLOAD_TIMEOUT_MS = 15_000
const NAMESPACE = 'product-skills'
// Revalidation keeps the current generation alive; superseded blobs expire naturally.
const DEFAULT_ARCHIVE_TTL_SECONDS = 30 * 24 * 60 * 60

export type SkillArchiveCacheResult = 'fresh_hit' | 'stale_hit' | 'cold_refresh' | 'waited' | 'fallback'

export type SkillArchiveRefreshResult = 'fresh' | 'not_modified' | 'downloaded' | 'lock_busy' | 'missing'

export interface SkillArchiveLoadResult {
    bytes: Uint8Array
    sha: string
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
    /**
     * Rejects downloaded bytes before they reach Redis. A throw keeps the previous
     * shared copy, so one bad release cannot take every pod's catalog with it.
     */
    validateArchive?: (bytes: Uint8Array) => void
}

/**
 * Redis-backed shared copy of the published skills.zip.
 *
 * Request handling never touches this class. A pod reads the archive once at
 * startup (`loadOrRefresh`), then a background poller asks for the small version
 * pointer (`readIfChanged`) and reads the bytes again only when the sha moved.
 * Staleness is repaired by whichever poller wins the writer lock
 * (`refreshIfStale`), with a conditional request so an unchanged release costs
 * a 304 and no bytes.
 */
export class SkillArchiveCache extends SharedBlobCache {
    private readonly archiveUrl: string
    private readonly fetchArchive: (url: string, etag?: string) => Promise<SkillArchiveFetchResult>
    private readonly validateArchive: (bytes: Uint8Array) => void

    constructor(redis: RedisLike, opts: SkillArchiveCacheOptions = {}) {
        const archiveUrl = opts.archiveUrl ?? DEFAULT_SKILL_ARCHIVE_URL
        const namespace =
            archiveUrl === DEFAULT_SKILL_ARCHIVE_URL
                ? NAMESPACE
                : `${NAMESPACE}:${createHash('sha256').update(archiveUrl).digest('hex').slice(0, 16)}`
        super(redis, namespace, { cacheTtlSeconds: DEFAULT_ARCHIVE_TTL_SECONDS, ...opts })
        this.archiveUrl = archiveUrl
        this.fetchArchive = opts.fetchArchive ?? downloadArchive
        this.validateArchive = opts.validateArchive ?? (() => undefined)
    }

    /**
     * Startup read. Serves the shared copy whether or not it is fresh — the poller
     * owns freshness — and downloads from the source only when the fleet has no
     * copy at all. Then one pod writes while the others wait for its result.
     */
    async loadOrRefresh(): Promise<SkillArchiveLoadResult> {
        const cached = await this.readCache()
        if (cached) {
            return { bytes: cached.bytes, sha: cached.sha, result: cached.fresh ? 'fresh_hit' : 'stale_hit' }
        }

        const token = randomUUID()
        if (await this.acquireLock(token)) {
            try {
                const { bytes, etag } = await this.downloadFull()
                const { sha } = await this.writeCache(bytes, etag)
                return { bytes, sha, result: 'cold_refresh' }
            } finally {
                await this.releaseLock(token)
            }
        }

        const waited = await this.waitForRecord()
        if (waited) {
            return { bytes: waited.bytes, sha: waited.sha, result: 'waited' }
        }
        const { bytes } = await this.downloadFull()
        return { bytes, sha: hashBytes(bytes), result: 'fallback' }
    }

    /** The shared copy's bytes when its sha differs from `currentSha`, else null. Reads the small pointer first. */
    async readIfChanged(currentSha: string | undefined): Promise<{ bytes: Uint8Array; sha: string } | null> {
        const version = await this.readVersion()
        if (!version || version.sha === currentSha) {
            return null
        }
        const cached = await this.readCache(version)
        if (!cached) {
            return null
        }
        return { bytes: cached.bytes, sha: cached.sha }
    }

    /**
     * Refreshes the shared copy from the source when it is past its fresh window.
     * At most one pod does the network work; the rest see `lock_busy` and pick up
     * the new sha on their next poll. `missing` means the fleet has no copy, which
     * `loadOrRefresh` repairs.
     */
    async refreshIfStale(): Promise<SkillArchiveRefreshResult> {
        const version = await this.readVersion()
        if (!version) {
            return 'missing'
        }
        if ((await this.redis.ttl(this.blobKey(version.sha))) === -2) {
            return 'missing'
        }
        if (version.fresh) {
            return 'fresh'
        }

        const token = randomUUID()
        if (!(await this.acquireLock(token))) {
            return 'lock_busy'
        }
        try {
            return await this.refreshUnderLock(version)
        } finally {
            await this.releaseLock(token)
        }
    }

    private async refreshUnderLock(version: SharedBlobVersion): Promise<SkillArchiveRefreshResult> {
        const result = await this.fetchArchiveChecked(version.etag)
        if (result.status === 'not_modified') {
            // Archive unchanged since we cached it: bump freshness and re-extend
            // the hard TTLs in place, skipping the re-download and re-parse.
            return (await this.touchCache(version)) ? 'not_modified' : 'missing'
        }
        await this.writeCache(result.bytes, result.etag)
        return 'downloaded'
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
        if (result.status === 'downloaded') {
            if (result.bytes.length === 0 || result.bytes.length > MAX_ARCHIVE_BYTES) {
                throw new Error(`Invalid skill archive size: ${result.bytes.length} bytes`)
            }
            this.validateArchive(result.bytes)
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
