import { mocked } from 'ts-jest/utils'

import { createServer } from '../../../src/shared/server'
import { PluginsServer } from '../../../src/types'
import { TeamManager } from '../../../src/worker/ingestion/team-manager'
import { resetTestDatabase } from '../../helpers/sql'

describe('TeamManager()', () => {
    let server: PluginsServer
    let closeServer: () => Promise<void>
    let teamManager: TeamManager

    beforeEach(async () => {
        ;[server, closeServer] = await createServer()
        await resetTestDatabase()
        teamManager = new TeamManager(server.db)
    })
    afterEach(async () => {
        await closeServer()
    })

    describe('fetchTeam()', () => {
        it('fetches and caches the team', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())
            jest.spyOn(server.db, 'postgresQuery')

            let team = await teamManager.fetchTeam(2, 'uuid1')
            expect(team!.name).toEqual('TEST PROJECT')
            expect(team!.__fetch_event_uuid).toEqual('uuid1')

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:25').getTime())
            await server.db.postgresQuery("UPDATE posthog_team SET name = 'Updated Name!'")

            mocked(server.db.postgresQuery).mockClear()

            team = await teamManager.fetchTeam(2, 'uuid2')
            expect(team!.name).toEqual('TEST PROJECT')
            expect(team!.__fetch_event_uuid).toEqual('uuid1')
            expect(server.db.postgresQuery).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:36').getTime())

            team = await teamManager.fetchTeam(2, 'uuid3')
            expect(team!.name).toEqual('Updated Name!')
            expect(team!.__fetch_event_uuid).toEqual('uuid3')

            expect(server.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        it('returns null when no such team', async () => {
            expect(await teamManager.fetchTeam(-1)).toEqual(null)
        })
    })

    describe('shouldSendWebhooks()', () => {
        it('returns false if unknown team', async () => {
            expect(await teamManager.shouldSendWebhooks(-1)).toEqual(false)
        })

        it('returns false if no hooks set up and team.slack_incoming_webhook == false', async () => {
            expect(await teamManager.shouldSendWebhooks(2)).toEqual(false)
        })

        it('returns true if hooks are set up', async () => {
            await server.db.postgresQuery('UPDATE posthog_team SET slack_incoming_webhook = true')
            await server.db.postgresQuery(
                "INSERT INTO ee_hook (id, team_id, user_id, event, target, created, updated) VALUES('test_hook', 2, 1001, 'action_performed', 'http://example.com', now(), now())"
            )

            expect(await teamManager.shouldSendWebhooks(2)).toEqual(true)
        })

        it('caches results', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())
            jest.spyOn(server.db, 'postgresQuery')
            expect(await teamManager.shouldSendWebhooks(2)).toEqual(false)

            await server.db.postgresQuery('UPDATE posthog_team SET slack_incoming_webhook = true')
            await server.db.postgresQuery(
                "INSERT INTO ee_hook (id, team_id, user_id, event, target, created, updated) VALUES('test_hook', 2, 1001, 'action_performed', 'http://example.com', now(), now())"
            )
            mocked(server.db.postgresQuery).mockClear()

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:25').getTime())
            expect(await teamManager.shouldSendWebhooks(2)).toEqual(false)
            expect(server.db.postgresQuery).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:45').getTime())
            expect(await teamManager.shouldSendWebhooks(2)).toEqual(true)
            expect(server.db.postgresQuery).toHaveBeenCalledTimes(2)
        })
    })

    describe('updateEventNamesAndProperties()', () => {
        let posthog: any

        beforeEach(async () => {
            posthog = { capture: jest.fn(), identify: jest.fn() }
            await server.db.postgresQuery(
                `
                UPDATE posthog_team SET
                    ingested_event = $1,
                    event_names = $2,
                    event_names_with_usage = $3,
                    event_properties = $4,
                    event_properties_with_usage = $5,
                    event_properties_numerical = $6`,
                [
                    true,
                    JSON.stringify(['$pageview']),
                    JSON.stringify([{ event: '$pageview', usage_count: 2, volume: 3 }]),
                    JSON.stringify(['property_name', 'numeric_prop']),
                    JSON.stringify([
                        { key: 'property_name', usage_count: null, volume: null },
                        { key: 'numeric_prop', usage_count: null, volume: null },
                    ]),
                    JSON.stringify(['numeric_prop']),
                ]
            )
        })

        it('updates event properties', async () => {
            await teamManager.updateEventNamesAndProperties(
                2,
                'new-event',
                '',
                { property_name: 'efg', number: 4, numeric_prop: 5 },
                posthog
            )
            teamManager.teamCache.clear()

            const team = await teamManager.fetchTeam(2)
            expect(team?.event_names).toEqual(['$pageview', 'new-event'])
            expect(team?.event_names_with_usage).toEqual([
                { event: '$pageview', usage_count: 2, volume: 3 },
                { event: 'new-event', usage_count: null, volume: null },
            ])
            expect(team?.event_properties).toEqual(['property_name', 'numeric_prop', 'number'])
            expect(team?.event_properties_with_usage).toEqual([
                { key: 'property_name', usage_count: null, volume: null },
                { key: 'numeric_prop', usage_count: null, volume: null },
                { key: 'number', usage_count: null, volume: null },
            ])
            expect(team?.event_properties_numerical).toEqual(['numeric_prop', 'number'])
        })

        it('does not update anything if nothing changes', async () => {
            await teamManager.fetchTeam(2, 'uuid1')
            jest.spyOn(server.db, 'postgresQuery')

            await teamManager.updateEventNamesAndProperties(2, '$pageview', '', {}, posthog)

            expect(server.db.postgresQuery).not.toHaveBeenCalled()
        })

        it('does not capture event', async () => {
            await teamManager.updateEventNamesAndProperties(
                2,
                'new-event',
                '',
                { property_name: 'efg', number: 4 },
                posthog
            )

            expect(posthog.identify).not.toHaveBeenCalled()
            expect(posthog.capture).not.toHaveBeenCalled()
        })

        it('handles cache invalidation properly', async () => {
            await teamManager.fetchTeam(2, 'uuid1')
            await server.db.postgresQuery('UPDATE posthog_team SET event_names = $1', [
                JSON.stringify(['$pageview', '$foobar']),
            ])

            jest.spyOn(teamManager, 'fetchTeam')
            jest.spyOn(server.db, 'postgresQuery')

            // Scenario: Different request comes in, team gets reloaded in the background with no updates
            await teamManager.updateEventNamesAndProperties(2, '$foobar', 'uuid2', {}, posthog)
            expect(teamManager.fetchTeam).toHaveBeenCalledTimes(2)
            expect(server.db.postgresQuery).toHaveBeenCalledTimes(1)

            // Scenario: Next request but a real update
            mocked(teamManager.fetchTeam).mockClear()
            mocked(server.db.postgresQuery).mockClear()

            await teamManager.updateEventNamesAndProperties(2, '$newevent', 'uuid2', {}, posthog)
            expect(teamManager.fetchTeam).toHaveBeenCalledTimes(1)
            expect(server.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        describe('first event has not yet been ingested', () => {
            beforeEach(async () => {
                await server.db.postgresQuery('UPDATE posthog_team SET ingested_event = false')
            })

            it('calls posthog.identify and posthog.capture', async () => {
                await teamManager.updateEventNamesAndProperties(2, 'new-event', '', {}, posthog)

                const team = await teamManager.fetchTeam(2, 'uuid1')
                expect(posthog.identify).toHaveBeenCalledWith('plugin_test_user_distinct_id_1001')
                expect(posthog.capture).toHaveBeenCalledWith('first team event ingested', { team: team!.uuid })
            })
        })
    })
})
