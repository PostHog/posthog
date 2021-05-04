import { makeWorkerUtils } from 'graphile-worker'
import { Pool } from 'pg'

import { PluginsServerConfig } from '../../src/types'

export async function resetGraphileSchema(server: PluginsServerConfig): Promise<void> {
    const graphileUrl = server.JOB_QUEUE_GRAPHILE_URL || server.DATABASE_URL
    const db = new Pool({ connectionString: graphileUrl })

    try {
        await db.query('DROP SCHEMA graphile_worker CASCADE')
    } catch (error) {
        if (error.message !== 'schema "graphile_worker" does not exist') {
            throw error
        }
    } finally {
        await db.end()
    }

    const workerUtils = await makeWorkerUtils({
        connectionString: graphileUrl,
    })
    await workerUtils.migrate()
    await workerUtils.release()
}
