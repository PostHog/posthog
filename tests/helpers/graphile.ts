import { makeWorkerUtils } from 'graphile-worker'
import { Pool } from 'pg'

import { defaultConfig } from '../../src/shared/config'
import { status } from '../../src/shared/status'

export async function resetGraphileSchema(): Promise<void> {
    const db = new Pool({ connectionString: defaultConfig.DATABASE_URL })

    try {
        await db.query('DROP SCHEMA graphile_worker CASCADE')
    } catch (e) {
        status.error('😱', `Could not dump graphile_worker schema: ${e.message}`)
    } finally {
        await db.end()
    }

    const workerUtils = await makeWorkerUtils({
        connectionString: defaultConfig.DATABASE_URL,
    })
    await workerUtils.migrate()
    await workerUtils.release()
}
