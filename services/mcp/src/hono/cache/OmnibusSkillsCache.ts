import { SkillCatalog } from '@/skills/skill-catalog'

import type { RedisLike } from './RedisCache'
import { hashBytes, SharedBlobCache, type SharedBlobCacheOptions } from './SharedBlobCache'

const NAMESPACE = 'omnibus-skills'
const DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60

export class OmnibusSkillsCache extends SharedBlobCache {
    constructor(redis: RedisLike, opts: SharedBlobCacheOptions = {}) {
        super(redis, NAMESPACE, { cacheTtlSeconds: DEFAULT_TTL_SECONDS, ...opts })
    }

    /** Parses before publishing, so a release the catalog cannot load never becomes the shared copy. */
    async publish(bytes: Uint8Array): Promise<void> {
        SkillCatalog.fromZip(bytes)
        const current = await this.readVersion()
        if (current?.sha === hashBytes(bytes) && (await this.touchCache(current))) {
            return
        }
        await this.writeCache(bytes)
    }

    async readIfChanged(currentSha: string | undefined): Promise<{ bytes: Uint8Array; sha: string } | null> {
        const version = await this.readVersion()
        if (!version || version.sha === currentSha) {
            return null
        }
        const cached = await this.readCache(version)
        return cached ? { bytes: cached.bytes, sha: cached.sha } : null
    }
}
