import { SkillCatalog } from '@/skills/skill-catalog'

import type { RedisLike } from './cache/RedisCache'
import { SkillArchiveCache, type SkillArchiveCacheOptions } from './cache/SkillArchiveCache'
import {
    skillArchiveEventsTotal,
    skillArchiveLastValidatedTimestampSeconds,
    skillCatalogAgeSeconds,
    skillCatalogLoadDurationSeconds,
    skillCatalogSkills,
} from './metrics'

const DEFAULT_POLL_INTERVAL_MS = 60_000
const DEFAULT_POLL_JITTER_MS = 15_000
const DEFAULT_WARMUP_TIMEOUT_MS = 60_000
const DEFAULT_WARMUP_RETRY_MS = 2_000

export interface SkillCatalogServiceOptions extends SkillArchiveCacheOptions {
    /** Base interval between polls of the shared version key. */
    pollIntervalMs?: number
    /** Random extra per pod, so a fleet does not poll in lockstep. */
    pollJitterMs?: number
    /** How long startup waits for a catalog before the pod serves without one. */
    warmupTimeoutMs?: number
    warmupRetryMs?: number
}

type LoadPhase = 'warmup' | 'poll'

/**
 * Holds the parsed product skill catalog for this pod.
 *
 * Requests only ever read `getCatalog()` from memory. Startup blocks on the first
 * load, then `start()` runs a background poller that adopts a newer shared
 * archive and refreshes the shared copy when it is stale. A failed refresh or a
 * bad archive keeps the last catalog that parsed.
 */
export class SkillCatalogService {
    private readonly archiveCache: SkillArchiveCache
    private readonly pollIntervalMs: number
    private readonly pollJitterMs: number
    private readonly warmupTimeoutMs: number
    private readonly warmupRetryMs: number

    private catalog: SkillCatalog | undefined
    private archiveSha: string | undefined
    private loadedAt: number | undefined
    private timer: ReturnType<typeof setInterval> | undefined
    private polling = false

    constructor(redis: RedisLike, opts: SkillCatalogServiceOptions = {}) {
        const { pollIntervalMs, pollJitterMs, warmupTimeoutMs, warmupRetryMs, ...cacheOptions } = opts
        this.archiveCache = new SkillArchiveCache(redis, {
            ...cacheOptions,
            // Parse before the bytes can reach Redis: a release that does not parse
            // never becomes the fleet's shared copy.
            validateArchive: cacheOptions.validateArchive ?? ((bytes) => void SkillCatalog.fromZip(bytes)),
        })
        this.pollIntervalMs = pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS
        this.pollJitterMs = pollJitterMs ?? DEFAULT_POLL_JITTER_MS
        this.warmupTimeoutMs = warmupTimeoutMs ?? DEFAULT_WARMUP_TIMEOUT_MS
        this.warmupRetryMs = warmupRetryMs ?? DEFAULT_WARMUP_RETRY_MS
    }

    getCatalog(): SkillCatalog | undefined {
        return this.catalog
    }

    /**
     * Blocks boot until a catalog is in memory, retrying inside a fixed budget.
     * Past the budget the pod starts without skills rather than holding the whole
     * fleet unready during a source and Redis outage; the poller keeps trying.
     */
    async warmup(): Promise<void> {
        const deadline = Date.now() + this.warmupTimeoutMs
        for (;;) {
            try {
                const loaded = await this.archiveCache.loadOrRefresh()
                skillArchiveEventsTotal.inc({ phase: 'warmup', result: loaded.result })
                this.install(loaded.bytes, loaded.sha, 'warmup')
                return
            } catch (error) {
                skillArchiveEventsTotal.inc({ phase: 'warmup', result: 'error' })
                if (Date.now() + this.warmupRetryMs >= deadline) {
                    console.error('[SkillCatalogService] warmup failed; starting without product skills:', error)
                    return
                }
                console.error('[SkillCatalogService] warmup attempt failed; retrying:', error)
                await sleep(this.warmupRetryMs)
            } finally {
                skillArchiveLastValidatedTimestampSeconds.set((this.archiveCache.getLastValidatedAt() ?? 0) / 1000)
            }
        }
    }

    /** Starts the background poller. Idempotent; the timer never keeps the process alive. */
    start(): void {
        if (this.timer) {
            return
        }
        const interval = this.pollIntervalMs + Math.floor(Math.random() * this.pollJitterMs)
        this.timer = setInterval(() => void this.poll(), interval)
        this.timer.unref?.()
    }

    stop(): void {
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = undefined
        }
    }

    /**
     * One poll: adopt a newer shared archive, then repair the shared copy if it is
     * stale or missing. Overlapping polls collapse into one.
     */
    async poll(): Promise<void> {
        if (this.polling) {
            return
        }
        this.polling = true
        try {
            await this.adoptSharedArchive()
            const refresh = await this.archiveCache.refreshIfStale()
            skillArchiveEventsTotal.inc({ phase: 'poll', result: refresh })
            if (refresh === 'downloaded') {
                await this.adoptSharedArchive()
            } else if (refresh === 'missing') {
                const loaded = await this.archiveCache.loadOrRefresh()
                skillArchiveEventsTotal.inc({ phase: 'poll', result: loaded.result })
                this.install(loaded.bytes, loaded.sha, 'poll')
            }
        } catch (error) {
            skillArchiveEventsTotal.inc({ phase: 'poll', result: 'error' })
            console.error('[SkillCatalogService] poll failed; keeping the current catalog:', error)
        } finally {
            this.polling = false
            skillArchiveLastValidatedTimestampSeconds.set((this.archiveCache.getLastValidatedAt() ?? 0) / 1000)
            if (this.loadedAt !== undefined) {
                skillCatalogAgeSeconds.set((Date.now() - this.loadedAt) / 1000)
            }
        }
    }

    private async adoptSharedArchive(): Promise<void> {
        const changed = await this.archiveCache.readIfChanged(this.archiveSha)
        if (!changed) {
            return
        }
        skillArchiveEventsTotal.inc({ phase: 'poll', result: 'reloaded' })
        this.install(changed.bytes, changed.sha, 'poll')
    }

    private install(bytes: Uint8Array, sha: string, phase: LoadPhase): void {
        if (sha === this.archiveSha) {
            return
        }
        const start = Date.now()
        const catalog = SkillCatalog.fromZip(bytes)
        this.catalog = catalog
        this.archiveSha = sha
        this.loadedAt = Date.now()
        skillCatalogLoadDurationSeconds.observe({ phase }, (this.loadedAt - start) / 1000)
        skillCatalogSkills.set(catalog.size)
        skillCatalogAgeSeconds.set(0)
        console.info(`[SkillCatalogService] installed ${catalog.size} skills (${phase}, sha ${sha.slice(0, 12)})`)
    }
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}
