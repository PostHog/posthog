import { createHash } from 'node:crypto'

import { SkillCatalog } from '@/skills/skill-catalog'

import type { RedisLike } from './cache/RedisCache'
import { SkillArchiveCache, type SkillArchiveCacheOptions } from './cache/SkillArchiveCache'

/** Keeps the last valid parsed catalog available when refreshes fail. */
export class SkillCatalogService {
    private readonly archiveCache: SkillArchiveCache
    private catalog: SkillCatalog | undefined
    private archiveHash: string | undefined

    constructor(redis: RedisLike, opts: SkillArchiveCacheOptions = {}) {
        this.archiveCache = new SkillArchiveCache(redis, opts)
    }

    getCatalog(): SkillCatalog | undefined {
        return this.catalog
    }

    async warmup(): Promise<void> {
        await this.loadSafely('warmup')
    }

    async revalidate(): Promise<void> {
        await this.loadSafely('revalidation')
    }

    private async loadSafely(operation: string): Promise<void> {
        try {
            const { bytes } = await this.archiveCache.loadOrRefresh()
            const hash = createHash('sha256').update(bytes).digest('hex')
            if (hash === this.archiveHash) {
                return
            }
            const catalog = SkillCatalog.fromZip(bytes)
            this.catalog = catalog
            this.archiveHash = hash
        } catch (error) {
            console.error(`[SkillCatalogService] ${operation} failed; continuing without refreshed skills:`, error)
        }
    }
}
