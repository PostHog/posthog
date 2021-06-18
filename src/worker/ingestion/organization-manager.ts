import { RawOrganization } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'

type OrganizationCache<T> = Map<RawOrganization['id'], [T, number]>

export class OrganizationManager {
    db: DB
    organizationCache: OrganizationCache<RawOrganization | null>

    constructor(db: DB) {
        this.db = db
        this.organizationCache = new Map()
    }

    public async fetchOrganization(organizationId: RawOrganization['id']): Promise<RawOrganization | null> {
        const cachedOrganization = this.getByAge(this.organizationCache, organizationId)
        if (cachedOrganization) {
            return cachedOrganization
        }

        const timeout = timeoutGuard(`Still running "fetchOrganization". Timeout warning after 30 sec!`)
        try {
            const organization: RawOrganization | null = (await this.db.fetchOrganization(organizationId)) || null
            this.organizationCache.set(organizationId, [organization, Date.now()])
            return organization
        } finally {
            clearTimeout(timeout)
        }
    }

    private getByAge<K, V>(cache: Map<K, [V, number]>, key: K, maxAgeMs = 30_000): V | undefined {
        if (cache.has(key)) {
            const [value, age] = cache.get(key)!
            if (Date.now() - age <= maxAgeMs) {
                return value
            }
        }
        return undefined
    }
}
