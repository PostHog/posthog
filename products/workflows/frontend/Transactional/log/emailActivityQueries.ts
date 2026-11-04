import api from 'lib/api'
import { hogql } from 'lib/utils/hogql'

import { ActivityPerson } from './emailActivity'

const QUERY_TAGS = { productKey: 'workflows', scene: 'TransactionalEmailLogEntry' }

export async function fetchActivityPerson(distinctId: string): Promise<ActivityPerson | null> {
    const response = await api.queryHogQL(
        hogql`SELECT id, properties, created_at
FROM persons
WHERE id IN (SELECT person_id FROM person_distinct_ids WHERE distinct_id = ${distinctId})
LIMIT 1`,
        QUERY_TAGS
    )
    const row = response.results?.[0]
    if (!row) {
        return null
    }
    const [id, properties, createdAt] = row
    return {
        id,
        properties: typeof properties === 'string' ? JSON.parse(properties) : (properties ?? {}),
        createdAt,
    }
}
