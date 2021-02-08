import { DateTime } from 'luxon'

import { createPosthog, DummyPostHog } from '../../src/extensions/posthog'
import { startPluginsServer } from '../../src/server'
import { Database, LogLevel, PluginsServer, PluginsServerConfig, Team, TimestampFormat } from '../../src/types'
import { castTimestampOrNow, UUIDT } from '../../src/utils'
import { makePiscina } from '../../src/worker/piscina'
import { resetTestDatabaseClickhouse } from '../helpers/clickhouse'
import { resetKafka } from '../helpers/kafka'
import { pluginConfig39 } from '../helpers/plugins'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'
import { delayUntilEventIngested } from '../shared/process-event'

jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    KAFKA_ENABLED: true,
    KAFKA_HOSTS: process.env.KAFKA_HOSTS || 'kafka:9092',
    WORKER_CONCURRENCY: 2,
    PLUGIN_SERVER_INGESTION: true,
    LOG_LEVEL: LogLevel.Log,
}

describe('postgres parity', () => {
    let server: PluginsServer
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
    let team: Team

    beforeAll(async () => {
        await resetKafka(extraServerConfig)
    })

    beforeEach(async () => {
        await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
        `)
        await resetTestDatabaseClickhouse(extraServerConfig)
        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        server = startResponse.server
        stopServer = startResponse.stop
        posthog = createPosthog(server, pluginConfig39)
        team = await getFirstTeam(server)
    })

    afterEach(async () => {
        await stopServer()
    })

    test('createPerson', async () => {
        const uuid = new UUIDT().toString()
        const person = await server.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            team.id,
            null,
            true,
            uuid,
            ['distinct1', 'distinct2']
        )
        await delayUntilEventIngested(() => server.db.fetchPersons(Database.ClickHouse))
        await delayUntilEventIngested(() => server.db.fetchDistinctIdValues(person, Database.ClickHouse), 2)

        const clickHousePersons = await server.db.fetchPersons(Database.ClickHouse)
        expect(clickHousePersons).toEqual([
            {
                id: uuid,
                created_at: expect.any(String), // '2021-02-04 00:18:26.472',
                team_id: team.id,
                properties: '{"userProp":"propValue"}',
                is_identified: 1,
                _timestamp: expect.any(String),
                _offset: expect.any(Number),
            },
        ])
        const clickHouseDistinctIds = await server.db.fetchDistinctIdValues(person, Database.ClickHouse)
        expect(clickHouseDistinctIds).toEqual(['distinct1', 'distinct2'])

        const postgresPersons = await server.db.fetchPersons(Database.Postgres)
        expect(postgresPersons).toEqual([
            {
                id: expect.any(Number),
                created_at: expect.any(DateTime),
                properties: {
                    userProp: 'propValue',
                },
                team_id: 2,
                is_user_id: null,
                is_identified: true,
                uuid: uuid,
            },
        ])
        const postgresDistinctIds = await server.db.fetchDistinctIdValues(person, Database.Postgres)
        expect(postgresDistinctIds).toEqual(['distinct1', 'distinct2'])

        expect(person).toEqual(postgresPersons[0])
    })

    test('updatePerson', async () => {
        const uuid = new UUIDT().toString()
        const person = await server.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            team.id,
            null,
            false,
            uuid,
            ['distinct1', 'distinct2']
        )
        await delayUntilEventIngested(() => server.db.fetchPersons(Database.ClickHouse))
        await delayUntilEventIngested(() => server.db.fetchDistinctIdValues(person, Database.ClickHouse), 2)

        // update JSON and boolean to true

        await server.db.updatePerson(person, { properties: { replacedUserProp: 'propValue' }, is_identified: true })

        await delayUntilEventIngested(async () =>
            (await server.db.fetchPersons(Database.ClickHouse)).filter((p) => p.is_identified)
        )

        const clickHousePersons = await server.db.fetchPersons(Database.ClickHouse)
        const postgresPersons = await server.db.fetchPersons(Database.Postgres)

        expect(clickHousePersons.length).toEqual(1)
        expect(postgresPersons.length).toEqual(1)

        expect(postgresPersons[0].is_identified).toEqual(true)
        expect(postgresPersons[0].properties).toEqual({ replacedUserProp: 'propValue' })

        expect(clickHousePersons[0].is_identified).toEqual(1)
        expect(clickHousePersons[0].properties).toEqual('{"replacedUserProp":"propValue"}')

        // update date and boolean to false

        const randomDate = DateTime.utc().minus(100000).setZone('UTC')
        await server.db.updatePerson(person, { created_at: randomDate, is_identified: false })

        await delayUntilEventIngested(async () =>
            (await server.db.fetchPersons(Database.ClickHouse)).filter((p) => p.is_identified)
        )

        const clickHousePersons2 = await server.db.fetchPersons(Database.ClickHouse)
        const postgresPersons2 = await server.db.fetchPersons(Database.Postgres)

        expect(clickHousePersons2.length).toEqual(1)
        expect(postgresPersons2.length).toEqual(1)

        expect(postgresPersons2[0].is_identified).toEqual(false)
        expect(postgresPersons2[0].created_at.toISO()).toEqual(randomDate.toISO())

        expect(clickHousePersons2[0].is_identified).toEqual(0)
        expect(clickHousePersons2[0].created_at).toEqual(
            // TODO: get rid of `+ '.000'` by removing the need for ClickHouseSecondPrecision on CH persons
            castTimestampOrNow(randomDate, TimestampFormat.ClickHouseSecondPrecision) + '.000'
        )
    })

    test('deletePerson', async () => {
        const uuid = new UUIDT().toString()
        const person = await server.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            team.id,
            null,
            false,
            uuid,
            ['distinct1', 'distinct2']
        )
        await delayUntilEventIngested(() => server.db.fetchPersons(Database.ClickHouse))
        await delayUntilEventIngested(() => server.db.fetchDistinctIdValues(person, Database.ClickHouse), 2)

        await server.db.deletePerson(person)

        await delayUntilEventIngested(async () =>
            (await server.db.fetchPersons(Database.ClickHouse)).length === 0 ? ['deleted!'] : []
        )

        const clickHousePersons = await server.db.fetchPersons(Database.ClickHouse)
        const postgresPersons = await server.db.fetchPersons(Database.Postgres)

        expect(clickHousePersons.length).toEqual(0)
        expect(postgresPersons.length).toEqual(0)

        const clickHouseDistinctIdValues = await server.db.fetchDistinctIdValues(person, Database.ClickHouse)
        const postgresDistinctIdValues = await server.db.fetchDistinctIdValues(person, Database.Postgres)
        expect(clickHouseDistinctIdValues.length).toEqual(0)
        expect(postgresDistinctIdValues.length).toEqual(0)
    })

    test('addDistinctId & moveDistinctId', async () => {
        const uuid = new UUIDT().toString()
        const uuid2 = new UUIDT().toString()
        const person = await server.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            team.id,
            null,
            true,
            uuid,
            ['distinct1']
        )
        const anotherPerson = await server.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            team.id,
            null,
            true,
            uuid2,
            ['another_distinct_id']
        )
        await delayUntilEventIngested(() => server.db.fetchPersons(Database.ClickHouse))
        const [postgresPerson] = await server.db.fetchPersons(Database.Postgres)

        await delayUntilEventIngested(() => server.db.fetchDistinctIdValues(postgresPerson, Database.ClickHouse), 1)
        const clickHouseDistinctIdValues = await server.db.fetchDistinctIdValues(postgresPerson, Database.ClickHouse)
        const postgresDistinctIdValues = await server.db.fetchDistinctIdValues(postgresPerson, Database.Postgres)

        // check that all is in the right format

        expect(clickHouseDistinctIdValues).toEqual(['distinct1'])
        expect(postgresDistinctIdValues).toEqual(['distinct1'])

        const clickHouseDistinctIds = await server.db.fetchDistinctIds(postgresPerson, Database.ClickHouse)
        const postgresDistinctIds = await server.db.fetchDistinctIds(postgresPerson, Database.Postgres)

        expect(clickHouseDistinctIds).toEqual([
            {
                id: expect.any(Number),
                distinct_id: 'distinct1',
                person_id: person.uuid,
                team_id: team.id,
                _timestamp: expect.any(String),
                _offset: expect.any(Number),
            },
        ])
        expect(postgresDistinctIds).toEqual([
            {
                id: expect.any(Number),
                distinct_id: 'distinct1',
                person_id: person.id,
                team_id: team.id,
            },
        ])
        expect(clickHouseDistinctIds[0].id).toEqual(postgresDistinctIds[0].id)

        // add 'anotherOne' to person

        await server.db.addDistinctId(postgresPerson, 'anotherOne')

        await delayUntilEventIngested(() => server.db.fetchDistinctIdValues(postgresPerson, Database.ClickHouse), 2)

        const clickHouseDistinctIdValues2 = await server.db.fetchDistinctIdValues(postgresPerson, Database.ClickHouse)
        const postgresDistinctIdValues2 = await server.db.fetchDistinctIdValues(postgresPerson, Database.Postgres)

        expect(clickHouseDistinctIdValues2).toEqual(['distinct1', 'anotherOne'])
        expect(postgresDistinctIdValues2).toEqual(['distinct1', 'anotherOne'])

        // check anotherPerson for their initial distinct id

        const clickHouseDistinctIdValuesOther = await server.db.fetchDistinctIdValues(
            anotherPerson,
            Database.ClickHouse
        )
        const postgresDistinctIdValuesOther = await server.db.fetchDistinctIdValues(anotherPerson, Database.Postgres)

        expect(clickHouseDistinctIdValuesOther).toEqual(['another_distinct_id'])
        expect(postgresDistinctIdValuesOther).toEqual(['another_distinct_id'])

        // move 'distinct1' from person to to anotherPerson

        await server.db.moveDistinctId(postgresPerson, postgresDistinctIds[0], anotherPerson)
        await delayUntilEventIngested(() => server.db.fetchDistinctIdValues(anotherPerson, Database.ClickHouse), 2)

        // it got added

        const clickHouseDistinctIdValuesMoved = await server.db.fetchDistinctIdValues(
            anotherPerson,
            Database.ClickHouse
        )
        const postgresDistinctIdValuesMoved = await server.db.fetchDistinctIdValues(anotherPerson, Database.Postgres)

        expect(clickHouseDistinctIdValuesMoved).toEqual(['distinct1', 'another_distinct_id'])
        expect(postgresDistinctIdValuesMoved).toEqual(['distinct1', 'another_distinct_id'])

        // it got removed

        const clickHouseDistinctIdValuesRemoved = await server.db.fetchDistinctIdValues(
            postgresPerson,
            Database.ClickHouse
        )
        const postgresDistinctIdValuesRemoved = await server.db.fetchDistinctIdValues(postgresPerson, Database.Postgres)

        // The `distinct1` key is still there in clickhouse, yet ALSO there for the new person.
        // Eventually this should be compacted away but it's not right now.
        expect(clickHouseDistinctIdValuesRemoved).toEqual(['distinct1', 'anotherOne'])
        expect(postgresDistinctIdValuesRemoved).toEqual(['anotherOne'])
    })
})
