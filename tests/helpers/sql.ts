import { Pool, PoolClient } from 'pg'

import { defaultConfig } from '../../src/config'
import { PluginsServer, PluginsServerConfig, Team } from '../../src/types'
import { delay, UUIDT } from '../../src/utils'
import { commonOrganizationId, commonOrganizationMembershipId, commonUserId, makePluginObjects } from './plugins'

export async function resetTestDatabase(
    code: string,
    extraServerConfig: Partial<PluginsServerConfig> = {}
): Promise<void> {
    const config = { ...defaultConfig, ...extraServerConfig }
    const db = new Pool({ connectionString: config.DATABASE_URL })
    const mocks = makePluginObjects(code)
    await db.query('DELETE FROM posthog_element')
    await db.query('DELETE FROM posthog_elementgroup')
    await db.query('DELETE FROM posthog_sessionrecordingevent')
    await db.query('DELETE FROM posthog_persondistinctid')
    await db.query('DELETE FROM posthog_person')
    await db.query('DELETE FROM posthog_event')
    await db.query('DELETE FROM posthog_pluginstorage')
    await db.query('DELETE FROM posthog_pluginattachment')
    await db.query('DELETE FROM posthog_pluginconfig')
    await db.query('DELETE FROM posthog_plugin')
    await db.query('DELETE FROM posthog_team')
    await db.query('DELETE FROM posthog_organizationmembership')
    await db.query('DELETE FROM posthog_organization')
    await db.query('DELETE FROM posthog_user')

    const teamIds = mocks.pluginConfigRows.map((c) => c.team_id)
    await createUserTeamAndOrganization(db, teamIds[0])

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
    try {
        await db.query(`INSERT INTO ${table} (${keys}) VALUES (${params})`, Object.values(object))
    } catch (error) {
        console.error(`Error on table ${table} when inserting object:\n`, object, '\n', error)
        throw error
    }
}

export async function createUserTeamAndOrganization(
    db: Pool,
    teamId: number,
    userId: number = commonUserId,
    organizationId: string = commonOrganizationId,
    organizationMembershipId: string = commonOrganizationMembershipId
): Promise<void> {
    await insertRow(db, 'posthog_user', {
        id: userId,
        password: 'gibberish',
        first_name: 'PluginTest',
        last_name: 'User',
        email: `test${userId}@posthog.com`,
        distinct_id: `plugin_test_user_distinct_id_${userId}`,
        is_staff: false,
        is_active: false,
        date_joined: new Date().toISOString(),
    })
    await insertRow(db, 'posthog_organization', {
        id: organizationId,
        name: 'TEST ORG',
        plugins_access_level: 9,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        personalization: '{}',
        setup_section_2_completed: true,
    })
    await insertRow(db, 'posthog_organizationmembership', {
        id: organizationMembershipId,
        organization_id: organizationId,
        user_id: userId,
        level: 15,
        joined_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    })
    await insertRow(db, 'posthog_team', {
        id: teamId,
        organization_id: organizationId,
        app_urls: [],
        name: 'TEST PROJECT',
        event_names: JSON.stringify([]),
        event_names_with_usage: JSON.stringify([]),
        event_properties: JSON.stringify([]),
        event_properties_with_usage: JSON.stringify([]),
        event_properties_numerical: JSON.stringify([]),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        anonymize_ips: false,
        completed_snippet_onboarding: true,
        ingested_event: true,
        uuid: new UUIDT().toString(),
        session_recording_opt_in: true,
        plugins_opt_in: true,
        opt_out_capture: false,
        is_demo: false,
        api_token: `THIS IS NOT A TOKEN FOR TEAM ${teamId}`,
        test_account_filters: [],
    })
}

export async function getTeams(server: PluginsServer): Promise<Team[]> {
    return (await server.db.postgresQuery('SELECT * FROM posthog_team ORDER BY id')).rows
}

export async function getFirstTeam(server: PluginsServer): Promise<Team> {
    return (await getTeams(server))[0]
}

/** Inject code onto `server` which runs a callback whenever a postgres query is performed */
export function onQuery(server: PluginsServer, onQueryCallback: (queryText: string) => any): void {
    function spyOnQueryFunction(client: any) {
        const query = client.query.bind(client)
        client.query = (queryText: any, values?: any, callback?: any): any => {
            onQueryCallback(queryText)
            return query(queryText, values, callback)
        }
    }

    spyOnQueryFunction(server.postgres)

    const postgresTransaction = server.db.postgresTransaction.bind(server.db)
    server.db.postgresTransaction = async (transaction: (client: PoolClient) => Promise<any>): Promise<any> => {
        return await postgresTransaction(async (client: PoolClient) => {
            const query = client.query
            spyOnQueryFunction(client)
            const response = await transaction(client)
            client.query = query
            return response
        })
    }
}
