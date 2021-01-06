import { makePluginObjects } from './plugins'
import { defaultConfig } from '../../src/config'
import { Pool } from 'pg'
import { delay } from '../../src/utils'

export async function resetTestDatabase(code: string): Promise<void> {
    const db = new Pool({ connectionString: defaultConfig.DATABASE_URL })
    const mocks = makePluginObjects(code)
    await db.query('DELETE FROM posthog_pluginstorage')
    await db.query('DELETE FROM posthog_pluginattachment')
    await db.query('DELETE FROM posthog_pluginconfig')
    await db.query('DELETE FROM posthog_plugin')
    await db.query('DELETE FROM posthog_team')

    const team_ids = mocks.pluginConfigRows.map((c) => c.team_id)
    for (const team_id of team_ids) {
        await insertRow(db, 'posthog_team', { id: team_id, name: 'TEST' })
    }
    for (const plugin of mocks.pluginRows) {
        await insertRow(db, 'posthog_plugin', plugin)
    }
    for (const pluginConfig of mocks.pluginConfigRows) {
        await insertRow(db, 'posthog_pluginconfig', pluginConfig)
    }
    for (const pluginAttachment of mocks.pluginAttachmentRows) {
        await insertRow(db, 'posthog_pluginattachment', pluginAttachment)
    }
    await delay(400)
    await db.end()
}

async function insertRow(db: Pool, table: string, object: Record<string, any>): Promise<void> {
    const keys = Object.keys(object)
        .map((key) => `"${key}"`)
        .join(',')
    const params = Object.keys(object)
        .map((_, i) => `\$${i + 1}`)
        .join(',')
    await db.query(`INSERT INTO ${table} (${keys}) VALUES (${params})`, Object.values(object))
}
