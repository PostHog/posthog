import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import * as IORedis from 'ioredis'
import { DateTime } from 'luxon'
import { performance } from 'perf_hooks'

import { IEvent } from '../../src/idl/protos'
import { hashElements } from '../../src/shared/ingestion/utils'
import { createServer } from '../../src/shared/server'
import { delay, UUIDT } from '../../src/shared/utils'
import {
    Database,
    Event,
    LogLevel,
    Person,
    PluginsServer,
    PluginsServerConfig,
    SessionRecordingEvent,
    Team,
} from '../../src/types'
import { EventsProcessor } from '../../src/worker/ingestion/process-event'
import { createUserTeamAndOrganization, getFirstTeam, getTeams, onQuery, resetTestDatabase } from '../helpers/sql'

jest.setTimeout(600000) // 600 sec timeout.

export async function delayUntilEventIngested(
    fetchEvents: () => Promise<any[] | any>,
    minCount = 1,
    delayMs = 500,
    maxDelayCount = 30,
    debug = false
): Promise<void> {
    const timer = performance.now()
    for (let i = 0; i < maxDelayCount; i++) {
        const events = await fetchEvents()
        if (debug) {
            console.log(
                `Waiting. ${Math.round((performance.now() - timer) / 100) / 10}s since the start. ${
                    typeof events === 'number' ? events : events.length
                } events.`
            )
        }
        if ((typeof events === 'number' ? events : events.length) >= minCount) {
            return
        }
        await delay(delayMs)
    }
}

async function createPerson(
    server: PluginsServer,
    team: Team,
    distinctIds: string[],
    properties: Record<string, any> = {}
): Promise<Person> {
    return server.db.createPerson(DateTime.utc(), properties, team.id, null, false, new UUIDT().toString(), distinctIds)
}

type ReturnWithServer = { server?: PluginsServer; stopServer?: () => Promise<void> }

export const createProcessEventTests = (
    database: 'postgresql' | 'clickhouse',
    extraServerConfig?: Partial<PluginsServerConfig>,
    createTests?: (response: ReturnWithServer) => void
): ReturnWithServer => {
    let queryCounter = 0
    let processEventCounter = 0
    let team: Team
    let server: PluginsServer
    let stopServer: () => Promise<void>
    let redis: IORedis.Redis
    let eventsProcessor: EventsProcessor
    let now = DateTime.utc()
    const returned: ReturnWithServer = {}

    async function getServer(): Promise<[PluginsServer, () => Promise<void>]> {
        const [server, stopServer] = await createServer({
            PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue',
            CELERY_DEFAULT_QUEUE: 'test-celery-default-queue',
            LOG_LEVEL: LogLevel.Log,
            ...(extraServerConfig ?? {}),
        })

        redis = await server.redisPool.acquire()

        await redis.del(server.PLUGINS_CELERY_QUEUE)
        await redis.del(server.CELERY_DEFAULT_QUEUE)

        onQuery(server, () => queryCounter++)

        return [server, stopServer]
    }

    async function processEvent(
        distinctId: string,
        ip: string | null,
        siteUrl: string,
        data: PluginEvent,
        teamId: number,
        now: DateTime,
        sentAt: DateTime | null,
        eventUuid: string
    ): Promise<IEvent | SessionRecordingEvent> {
        const response = await eventsProcessor.processEvent(
            distinctId,
            ip,
            siteUrl,
            data,
            teamId,
            now,
            sentAt,
            eventUuid
        )
        if (database === 'clickhouse') {
            await delayUntilEventIngested(() => server.db.fetchEvents(), ++processEventCounter)
        }
        return response
    }

    beforeEach(async () => {
        const testCode = `
            function processEvent (event, meta) {
                event.properties["somewhere"] = "over the rainbow";
                return event
            }
        `
        await resetTestDatabase(testCode, extraServerConfig)
        ;[server, stopServer] = await getServer()
        returned.server = server
        returned.stopServer = stopServer
        eventsProcessor = new EventsProcessor(server)
        queryCounter = 0
        processEventCounter = 0
        team = await getFirstTeam(server)
        now = DateTime.utc()

        // clear the webhook redis cache
        const hooksCacheKey = `@posthog/plugin-server/hooks/${team.id}`
        await redis.del(hooksCacheKey)
    })

    afterEach(async () => {
        await server.redisPool.release(redis)
        await stopServer?.()
    })

    createTests?.(returned)

    test('merge people', async () => {
        const p0 = await createPerson(server, team, ['person_0'], { $os: 'Microsoft' })
        if (database === 'clickhouse') {
            await delayUntilEventIngested(() => server.db.fetchPersons(Database.ClickHouse), 1)
        }

        await server.db.updatePerson(p0, { created_at: DateTime.fromISO('2020-01-01T00:00:00Z') })

        const p1 = await createPerson(server, team, ['person_1'], { $os: 'Chrome' })
        if (database === 'clickhouse') {
            await delayUntilEventIngested(() => server.db.fetchPersons(Database.ClickHouse), 2)
        }
        await server.db.updatePerson(p1, { created_at: DateTime.fromISO('2019-07-01T00:00:00Z') })

        await processEvent(
            'person_1',
            '',
            '',
            ({
                event: 'user signed up',
                properties: {},
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        await createPerson(server, team, ['person_2'], { $os: 'Apple', $browser: 'MS Edge' })
        await createPerson(server, team, ['person_3'], { $os: 'PlayStation' })

        if (database === 'clickhouse') {
            await delayUntilEventIngested(() => server.db.fetchPersons(Database.ClickHouse), 4)
            expect((await server.db.fetchPersons(Database.ClickHouse)).length).toEqual(4)
        }

        expect((await server.db.fetchPersons()).length).toEqual(4)
        const [person0, person1, person2, person3] = await server.db.fetchPersons()

        await eventsProcessor.mergePeople(person0, [person1, person2, person3])

        if (database === 'clickhouse') {
            await delayUntilEventIngested(async () =>
                (await server.db.fetchPersons(Database.ClickHouse)).length === 1 ? [1] : []
            )
            expect((await server.db.fetchPersons(Database.ClickHouse)).length).toEqual(1)
        }

        expect((await server.db.fetchPersons()).length).toEqual(1)

        const [person] = await server.db.fetchPersons()

        expect(person.properties).toEqual({ $os: 'Microsoft', $browser: 'MS Edge' })
        expect(await server.db.fetchDistinctIdValues(person)).toEqual(['person_0', 'person_1', 'person_2', 'person_3'])
        expect(person.created_at.toISO()).toEqual(DateTime.fromISO('2019-07-01T00:00:00Z').setZone('UTC').toISO())
    })

    test('capture new person', async () => {
        await server.db.postgresQuery(`UPDATE posthog_team SET ingested_event = $1 WHERE id = $2`, [true, team.id])
        team = await getFirstTeam(server)

        expect(team.event_names).toEqual([])

        await processEvent(
            '2',
            '127.0.0.1',
            '',
            ({
                event: '$autocapture',
                properties: {
                    distinct_id: 2,
                    token: team.api_token,
                    $browser: 'Chrome',
                    $current_url: 'https://test.com',
                    $os: 'Mac OS X',
                    $browser_version: 80,
                    $initial_referring_domain: 'https://google.com',
                    $initial_referrer_url: 'https://google.com/?q=posthog',
                    utm_medium: 'twitter',
                    $elements: [
                        { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
                        { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
                    ],
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        if (database === 'clickhouse') {
            expect(queryCounter).toBe(10)
        } else if (database === 'postgresql') {
            expect(queryCounter).toBe(14)
        }

        let persons = await server.db.fetchPersons()
        expect(persons[0].properties).toEqual({
            $initial_browser: 'Chrome',
            $initial_browser_version: 80,
            $initial_utm_medium: 'twitter',
            $initial_current_url: 'https://test.com',
            $initial_os: 'Mac OS X',
            utm_medium: 'twitter',
        })

        // capture a second time to verify e.g. event_names is not ['$autocapture', '$autocapture']
        // Also pass new utm params in to override
        await processEvent(
            '2',
            '127.0.0.1',
            '',
            ({
                event: '$autocapture',
                properties: {
                    distinct_id: 2,
                    token: team.api_token,
                    utm_medium: 'instagram',
                    $elements: [
                        { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
                        { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
                    ],
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        const events = await server.db.fetchEvents()
        persons = await server.db.fetchPersons()
        expect(events.length).toEqual(2)
        expect(persons.length).toEqual(1)
        expect(persons[0].properties).toEqual({
            $initial_browser: 'Chrome',
            $initial_browser_version: 80,
            $initial_utm_medium: 'twitter',
            $initial_current_url: 'https://test.com',
            $initial_os: 'Mac OS X',
            utm_medium: 'instagram',
        })

        const [person] = persons
        const distinctIds = await server.db.fetchDistinctIdValues(person)

        const [event] = events as Event[]
        expect(event.distinct_id).toEqual('2')
        expect(distinctIds).toEqual(['2'])
        expect(event.event).toEqual('$autocapture')

        const elements = await server.db.fetchElements(event)
        expect(elements[0].tag_name).toEqual('a')
        expect(elements[0].attr_class).toEqual(['btn', 'btn-sm'])
        expect(elements[1].order).toEqual(1)
        expect(elements[1].text).toEqual('💻')

        if (database === 'clickhouse') {
            expect(hashElements(elements)).toEqual('0679137c0cd2408a2906839143e7a71f')
        } else if (database === 'postgresql') {
            expect(event.elements_hash).toEqual('0679137c0cd2408a2906839143e7a71f')
        }

        team = await getFirstTeam(server)
        expect(team.event_names).toEqual(['$autocapture'])
        expect(team.event_names_with_usage).toEqual([{ event: '$autocapture', volume: null, usage_count: null }])
        expect(team.event_properties).toEqual([
            'distinct_id',
            'token',
            '$browser',
            '$current_url',
            '$os',
            '$browser_version',
            '$initial_referring_domain',
            '$initial_referrer_url',
            'utm_medium',
            '$ip',
        ])
        expect(team.event_properties_with_usage).toEqual([
            { key: 'distinct_id', usage_count: null, volume: null },
            { key: 'token', usage_count: null, volume: null },
            { key: '$browser', usage_count: null, volume: null },
            {
                key: '$current_url',
                usage_count: null,
                volume: null,
            },
            {
                key: '$os',
                usage_count: null,
                volume: null,
            },
            {
                key: '$browser_version',
                usage_count: null,
                volume: null,
            },
            {
                key: '$initial_referring_domain',
                usage_count: null,
                volume: null,
            },
            {
                key: '$initial_referrer_url',
                usage_count: null,
                volume: null,
            },
            {
                key: 'utm_medium',
                usage_count: null,
                volume: null,
            },
            { key: '$ip', usage_count: null, volume: null },
        ])
    })

    test('capture no element', async () => {
        await createPerson(server, team, ['asdfasdfasdf'])

        await processEvent(
            'asdfasdfasdf',
            '',
            '',
            ({
                event: '$pageview',
                properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect(await server.db.fetchDistinctIdValues((await server.db.fetchPersons())[0])).toEqual(['asdfasdfasdf'])
        const [event] = await server.db.fetchEvents()
        expect(event.event).toBe('$pageview')
    })

    test('capture sent_at', async () => {
        await createPerson(server, team, ['asdfasdfasdf'])

        const rightNow = DateTime.utc()
        const tomorrow = rightNow.plus({ days: 1, hours: 2 })
        const tomorrowSentAt = rightNow.plus({ days: 1, hours: 2, minutes: 10 })

        await processEvent(
            'movie played',
            '',
            '',
            ({
                event: '$pageview',
                timestamp: tomorrow.toISO(),
                properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
            } as any) as PluginEvent,
            team.id,
            rightNow,
            tomorrowSentAt,
            new UUIDT().toString()
        )

        const [event] = await server.db.fetchEvents()
        const eventSecondsBeforeNow = rightNow.diff(DateTime.fromISO(event.timestamp), 'seconds').seconds

        expect(eventSecondsBeforeNow).toBeGreaterThan(590)
        expect(eventSecondsBeforeNow).toBeLessThan(610)
    })

    test('capture sent_at no timezones', async () => {
        await createPerson(server, team, ['asdfasdfasdf'])

        const rightNow = DateTime.utc()
        const tomorrow = rightNow.plus({ days: 1, hours: 2 }).setZone('UTC+4')
        const tomorrowSentAt = rightNow.plus({ days: 1, hours: 2, minutes: 10 }).setZone('UTC+4')

        // TODO: not sure if this is correct?
        // tomorrow = tomorrow.replace(tzinfo=None)
        // tomorrow_sent_at = tomorrow_sent_at.replace(tzinfo=None)

        await processEvent(
            'movie played',
            '',
            '',
            ({
                event: '$pageview',
                timestamp: tomorrow,
                properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
            } as any) as PluginEvent,
            team.id,
            rightNow,
            tomorrowSentAt,
            new UUIDT().toString()
        )

        const [event] = await server.db.fetchEvents()
        const eventSecondsBeforeNow = rightNow.diff(DateTime.fromISO(event.timestamp), 'seconds').seconds

        expect(eventSecondsBeforeNow).toBeGreaterThan(590)
        expect(eventSecondsBeforeNow).toBeLessThan(610)
    })

    test('capture no sent_at', async () => {
        await createPerson(server, team, ['asdfasdfasdf'])

        const rightNow = DateTime.utc()
        const tomorrow = rightNow.plus({ days: 1, hours: 2 })

        await processEvent(
            'movie played',
            '',
            '',
            ({
                event: '$pageview',
                timestamp: tomorrow.toISO(),
                properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
            } as any) as PluginEvent,
            team.id,
            rightNow,
            null,
            new UUIDT().toString()
        )

        const [event] = await server.db.fetchEvents()
        const difference = tomorrow.diff(DateTime.fromISO(event.timestamp), 'seconds').seconds
        expect(difference).toBeLessThan(1)
    })

    test('ip none', async () => {
        await createPerson(server, team, ['asdfasdfasdf'])

        await processEvent(
            'asdfasdfasdf',
            null,
            '',
            ({
                event: '$pageview',
                properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        const [event] = await server.db.fetchEvents()
        expect(Object.keys(event.properties)).not.toContain('$ip')
    })

    test('ip capture', async () => {
        await createPerson(server, team, ['asdfasdfasdf'])

        await processEvent(
            'asdfasdfasdf',
            '11.12.13.14',
            '',
            ({
                event: '$pageview',
                properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        const [event] = await server.db.fetchEvents()
        expect(event.properties['$ip']).toBe('11.12.13.14')
    })

    test('ip override', async () => {
        await createPerson(server, team, ['asdfasdfasdf'])

        await processEvent(
            'asdfasdfasdf',
            '11.12.13.14',
            '',
            ({
                event: '$pageview',
                properties: { $ip: '1.0.0.1', distinct_id: 'asdfasdfasdf', token: team.api_token },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        const [event] = await server.db.fetchEvents()
        expect(event.properties['$ip']).toBe('1.0.0.1')
    })

    test('anonymized ip capture', async () => {
        await server.db.postgresQuery('update posthog_team set anonymize_ips = $1', [true])
        await createPerson(server, team, ['asdfasdfasdf'])

        await processEvent(
            'asdfasdfasdf',
            '11.12.13.14',
            '',
            ({
                event: '$pageview',
                properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        const [event] = await server.db.fetchEvents()
        expect(event.properties['$ip']).not.toBeDefined()
    })

    test('alias', async () => {
        await createPerson(server, team, ['old_distinct_id'])

        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$create_alias',
                properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)
        expect(await server.db.fetchDistinctIdValues((await server.db.fetchPersons())[0])).toEqual([
            'old_distinct_id',
            'new_distinct_id',
        ])
    })

    test('alias reverse', async () => {
        await createPerson(server, team, ['old_distinct_id'])

        await processEvent(
            'old_distinct_id',
            '',
            '',
            ({
                event: '$create_alias',
                properties: { distinct_id: 'old_distinct_id', token: team.api_token, alias: 'new_distinct_id' },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)
        expect(await server.db.fetchDistinctIdValues((await server.db.fetchPersons())[0])).toEqual([
            'old_distinct_id',
            'new_distinct_id',
        ])
    })

    test('alias twice', async () => {
        await createPerson(server, team, ['old_distinct_id'])

        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$create_alias',
                properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchPersons()).length).toBe(1)
        expect((await server.db.fetchEvents()).length).toBe(1)
        expect(await server.db.fetchDistinctIdValues((await server.db.fetchPersons())[0])).toEqual([
            'old_distinct_id',
            'new_distinct_id',
        ])

        await createPerson(server, team, ['old_distinct_id_2'])
        expect((await server.db.fetchPersons()).length).toBe(2)

        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$create_alias',
                properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id_2' },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        expect((await server.db.fetchEvents()).length).toBe(2)
        expect((await server.db.fetchPersons()).length).toBe(1)
        expect(await server.db.fetchDistinctIdValues((await server.db.fetchPersons())[0])).toEqual([
            'old_distinct_id',
            'new_distinct_id',
            'old_distinct_id_2',
        ])
    })

    test('alias before person', async () => {
        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$create_alias',
                properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)
        expect((await server.db.fetchPersons()).length).toBe(1)
        expect(await server.db.fetchDistinctIdValues((await server.db.fetchPersons())[0])).toEqual([
            'new_distinct_id',
            'old_distinct_id',
        ])
    })

    test('alias both existing', async () => {
        await createPerson(server, team, ['old_distinct_id'])
        await createPerson(server, team, ['new_distinct_id'])

        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$create_alias',
                properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)
        expect(await server.db.fetchDistinctIdValues((await server.db.fetchPersons())[0])).toEqual([
            'old_distinct_id',
            'new_distinct_id',
        ])
    })

    test('offset timestamp', async () => {
        now = DateTime.fromISO('2020-01-01T12:00:05.200Z')

        await processEvent(
            'distinct_id',
            '',
            '',
            ({ offset: 150, event: '$autocapture', distinct_id: 'distinct_id' } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        expect((await server.db.fetchEvents()).length).toBe(1)

        const [event] = await server.db.fetchEvents()
        expect(event.timestamp).toEqual('2020-01-01T12:00:05.050Z')
    })

    test('offset timestamp no sent_at', async () => {
        now = DateTime.fromISO('2020-01-01T12:00:05.200Z')

        await processEvent(
            'distinct_id',
            '',
            '',
            ({ offset: 150, event: '$autocapture', distinct_id: 'distinct_id' } as any) as PluginEvent,
            team.id,
            now,
            null,
            new UUIDT().toString()
        )
        expect((await server.db.fetchEvents()).length).toBe(1)

        const [event] = await server.db.fetchEvents()
        expect(event.timestamp).toEqual('2020-01-01T12:00:05.050Z')
    })

    test('alias merge properties', async () => {
        await createPerson(server, team, ['old_distinct_id'], {
            key_on_both: 'old value both',
            key_on_old: 'old value',
        })
        await createPerson(server, team, ['new_distinct_id'], {
            key_on_both: 'new value both',
            key_on_new: 'new value',
        })

        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$create_alias',
                properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)
        expect((await server.db.fetchPersons()).length).toBe(1)
        const [person] = await server.db.fetchPersons()
        expect(await server.db.fetchDistinctIdValues(person)).toEqual(['old_distinct_id', 'new_distinct_id'])
        expect(person.properties).toEqual({
            key_on_both: 'new value both',
            key_on_new: 'new value',
            key_on_old: 'old value',
        })
    })

    test('long htext', async () => {
        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$autocapture',
                properties: {
                    distinct_id: 'new_distinct_id',
                    token: team.api_token,
                    $elements: [
                        {
                            tag_name: 'a',
                            $el_text: 'a'.repeat(2050),
                            attr__href: 'a'.repeat(2050),
                            nth_child: 1,
                            nth_of_type: 2,
                            attr__class: 'btn btn-sm',
                        },
                    ],
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        const [event] = (await server.db.fetchEvents()) as Event[]
        const [element] = await server.db.fetchElements(event)
        expect(element.href?.length).toEqual(2048)
        expect(element.text?.length).toEqual(400)
        if (database === 'postgresql') {
            expect(event.elements_hash).toEqual('c2659b28e72835706835764cf7f63c2a')
        } else if (database === 'clickhouse') {
            expect(hashElements([element])).toEqual('c2659b28e72835706835764cf7f63c2a')
        }
    })

    test('capture first team event', async () => {
        await server.db.postgresQuery(`UPDATE posthog_team SET ingested_event = $1 WHERE id = $2`, [false, team.id])

        eventsProcessor.posthog = {
            identify: jest.fn((distinctId) => true),
            capture: jest.fn((event, properties) => true),
        } as any

        await processEvent(
            '2',
            '',
            '',
            ({
                event: '$autocapture',
                properties: {
                    distinct_id: 1,
                    token: team.api_token,
                    $elements: [{ tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' }],
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect(eventsProcessor.posthog.identify).toHaveBeenCalledWith('plugin_test_user_distinct_id_1001')
        expect(eventsProcessor.posthog.capture).toHaveBeenCalledWith('first team event ingested', {
            team: team.uuid,
        })

        team = await getFirstTeam(server)
        expect(team.ingested_event).toEqual(true)

        const [event] = (await server.db.fetchEvents()) as Event[]
        if (database === 'postgresql') {
            expect(event.elements_hash).toEqual('a89021a60b3497d24e93ae181fba01aa')
        } else if (database === 'clickhouse') {
            const elements = await server.db.fetchElements(event)
            expect(hashElements(elements)).toEqual('a89021a60b3497d24e93ae181fba01aa')
        }
    })

    test('snapshot event stored as session_recording_event', async () => {
        await eventsProcessor.processEvent(
            'some-id',
            '',
            '',
            ({
                event: '$snapshot',
                properties: { $session_id: 'abcf-efg', $snapshot_data: { timestamp: 123 } },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        await delayUntilEventIngested(() => server.db.fetchSessionRecordingEvents())

        const events = await server.db.fetchEvents()
        expect(events.length).toEqual(0)

        const sessionRecordingEvents = await server.db.fetchSessionRecordingEvents()
        expect(sessionRecordingEvents.length).toBe(1)

        const [event] = sessionRecordingEvents
        expect(event.session_id).toEqual('abcf-efg')
        expect(event.distinct_id).toEqual('some-id')
        expect(event.snapshot_data).toEqual({ timestamp: 123 })
    })

    test('identify set', async () => {
        await createPerson(server, team, ['distinct_id'])

        await processEvent(
            'distinct_id',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    token: team.api_token,
                    distinct_id: 'distinct_id',
                    $set: { a_prop: 'test-1', c_prop: 'test-1' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)

        const [event] = await server.db.fetchEvents()
        expect(event.properties['$set']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

        const [person] = await server.db.fetchPersons()
        expect(await server.db.fetchDistinctIdValues(person)).toEqual(['distinct_id'])
        expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })
        expect(person.is_identified).toEqual(true)

        await processEvent(
            'distinct_id',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    token: team.api_token,
                    distinct_id: 'distinct_id',
                    $set: { a_prop: 'test-2', b_prop: 'test-2b' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        expect((await server.db.fetchEvents()).length).toBe(2)
        const [person2] = await server.db.fetchPersons()
        expect(person2.properties).toEqual({ a_prop: 'test-2', b_prop: 'test-2b', c_prop: 'test-1' })
    })

    test('identify set_once', async () => {
        await createPerson(server, team, ['distinct_id'])

        await processEvent(
            'distinct_id',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    token: team.api_token,
                    distinct_id: 'distinct_id',
                    $set_once: { a_prop: 'test-1', c_prop: 'test-1' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)

        const [event] = await server.db.fetchEvents()
        expect(event.properties['$set_once']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

        const [person] = await server.db.fetchPersons()
        expect(await server.db.fetchDistinctIdValues(person)).toEqual(['distinct_id'])
        expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })
        expect(person.is_identified).toEqual(true)

        await processEvent(
            'distinct_id',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    token: team.api_token,
                    distinct_id: 'distinct_id',
                    $set_once: { a_prop: 'test-2', b_prop: 'test-2b' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        expect((await server.db.fetchEvents()).length).toBe(2)
        const [person2] = await server.db.fetchPersons()
        expect(person2.properties).toEqual({ a_prop: 'test-1', b_prop: 'test-2b', c_prop: 'test-1' })
    })

    test('distinct with anonymous_id', async () => {
        await createPerson(server, team, ['anonymous_id'])

        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    token: team.api_token,
                    distinct_id: 'new_distinct_id',
                    $set: { a_prop: 'test' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)
        const [event] = await server.db.fetchEvents()
        expect(event.properties['$set']).toEqual({ a_prop: 'test' })
        const [person] = await server.db.fetchPersons()
        expect(await server.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
        expect(person.properties).toEqual({ a_prop: 'test' })

        // check no errors as this call can happen multiple times
        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    token: team.api_token,
                    distinct_id: 'new_distinct_id',
                    $set: { a_prop: 'test' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
    })

    // This case is likely to happen after signup, for example:
    // 1. User browses website with anonymous_id
    // 2. User signs up, triggers event with their new_distinct_id (creating a new Person)
    // 3. In the frontend, try to alias anonymous_id with new_distinct_id
    // Result should be that we end up with one Person with both ID's
    test('distinct with anonymous_id which was already created', async () => {
        await createPerson(server, team, ['anonymous_id'])
        await createPerson(server, team, ['new_distinct_id'], { email: 'someone@gmail.com' })

        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    token: team.api_token,
                    distinct_id: 'new_distinct_id',
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        const [person] = await server.db.fetchPersons()
        expect(await server.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
        expect(person.properties['email']).toEqual('someone@gmail.com')
    })

    test('distinct with multiple anonymous_ids which were already created', async () => {
        await createPerson(server, team, ['anonymous_id'])
        await createPerson(server, team, ['new_distinct_id'], { email: 'someone@gmail.com' })

        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    $anon_distinct_id: 'anonymous_id',
                    token: team.api_token,
                    distinct_id: 'new_distinct_id',
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        const persons1 = await server.db.fetchPersons()
        expect(persons1.length).toBe(1)
        expect(await server.db.fetchDistinctIdValues(persons1[0])).toEqual(['anonymous_id', 'new_distinct_id'])
        expect(persons1[0].properties['email']).toEqual('someone@gmail.com')

        await createPerson(server, team, ['anonymous_id_2'])

        await processEvent(
            'new_distinct_id',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    $anon_distinct_id: 'anonymous_id_2',
                    token: team.api_token,
                    distinct_id: 'new_distinct_id',
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        const persons2 = await server.db.fetchPersons()
        expect(persons2.length).toBe(1)
        expect(await server.db.fetchDistinctIdValues(persons2[0])).toEqual([
            'anonymous_id',
            'new_distinct_id',
            'anonymous_id_2',
        ])
        expect(persons2[0].properties['email']).toEqual('someone@gmail.com')
    })

    test('distinct team leakage', async () => {
        await createUserTeamAndOrganization(
            server.postgres,
            3,
            1002,
            '01774e2f-0d01-0000-ee94-9a238640c6ee',
            '0174f81e-36f5-0000-7ef8-cc26c1fbab1c'
        )
        const team2 = (await getTeams(server))[1]
        await createPerson(server, team2, ['2'], { email: 'team2@gmail.com' })
        await createPerson(server, team, ['1', '2'])

        await processEvent(
            '2',
            '',
            '',
            ({
                event: '$identify',
                properties: {
                    $anon_distinct_id: '1',
                    token: team.api_token,
                    distinct_id: '2',
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        const people = await server.db.fetchPersons()
        expect(people.length).toEqual(2)
        expect(people[1].team_id).toEqual(team.id)
        expect(people[1].properties).toEqual({})
        expect(await server.db.fetchDistinctIdValues(people[1])).toEqual(['1', '2'])
        expect(people[0].team_id).toEqual(team2.id)
        expect(await server.db.fetchDistinctIdValues(people[0])).toEqual(['2'])
    })

    test('set is_identified', async () => {
        const distinct_id = '777'
        const person1 = await createPerson(server, team, [distinct_id])
        expect(person1.is_identified).toBe(false)

        await processEvent(
            distinct_id,
            '',
            '',
            ({ event: '$identify', properties: {} } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        const [person2] = await server.db.fetchPersons()
        expect(person2.is_identified).toBe(true)
    })

    test('team event_properties', async () => {
        expect(team.event_properties_numerical).toEqual([])

        await processEvent(
            'xxx',
            '127.0.0.1',
            '',
            ({ event: 'purchase', properties: { price: 299.99, name: 'AirPods Pro' } } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        team = await getFirstTeam(server)
        expect(team.event_properties).toEqual(['price', 'name', '$ip'])
        expect(team.event_properties_numerical).toEqual(['price'])
    })

    test('event name object json', async () => {
        await processEvent(
            'xxx',
            '',
            '',
            ({ event: { 'event name': 'as object' }, properties: {} } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        const [event] = await server.db.fetchEvents()
        expect(event.event).toEqual('{"event name":"as object"}')
    })

    test('event name array json', async () => {
        await processEvent(
            'xxx',
            '',
            '',
            ({ event: ['event name', 'a list'], properties: {} } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        const [event] = await server.db.fetchEvents()
        expect(event.event).toEqual('["event name","a list"]')
    })

    test('long event name substr', async () => {
        await processEvent(
            'xxx',
            '',
            '',
            ({ event: 'E'.repeat(300), properties: { price: 299.99, name: 'AirPods Pro' } } as any) as PluginEvent,
            team.id,
            DateTime.utc(),
            DateTime.utc(),
            new UUIDT().toString()
        )

        const [event] = await server.db.fetchEvents()
        expect(event.event?.length).toBe(200)
    })

    test('throws with bad uuid', async () => {
        await expect(
            processEvent(
                'xxx',
                '',
                '',
                ({ event: 'E', properties: { price: 299.99, name: 'AirPods Pro' } } as any) as PluginEvent,
                team.id,
                DateTime.utc(),
                DateTime.utc(),
                'this is not an uuid'
            )
        ).rejects.toEqual(new Error('Not a valid UUID: "this is not an uuid"'))

        await expect(
            processEvent(
                'xxx',
                '',
                '',
                ({ event: 'E', properties: { price: 299.99, name: 'AirPods Pro' } } as any) as PluginEvent,
                team.id,
                DateTime.utc(),
                DateTime.utc(),
                null as any
            )
        ).rejects.toEqual(new Error('Not a valid UUID: "null"'))
    })

    test('any event can do $set on props (user exists)', async () => {
        await createPerson(server, team, ['distinct_id'])

        await processEvent(
            'distinct_id',
            '',
            '',
            ({
                event: 'some_event',
                properties: {
                    token: team.api_token,
                    distinct_id: 'distinct_id',
                    $set: { a_prop: 'test-1', c_prop: 'test-1' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)

        const [event] = await server.db.fetchEvents()
        expect(event.properties['$set']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

        const [person] = await server.db.fetchPersons()
        expect(await server.db.fetchDistinctIdValues(person)).toEqual(['distinct_id'])
        expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })
    })

    test('any event can do $set on props (new user)', async () => {
        await processEvent(
            'distinct_id',
            '',
            '',
            ({
                event: 'some_event',
                properties: {
                    token: team.api_token,
                    distinct_id: 'distinct_id',
                    $set: { a_prop: 'test-1', c_prop: 'test-1' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)

        const [event] = await server.db.fetchEvents()
        expect(event.properties['$set']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

        const [person] = await server.db.fetchPersons()
        expect(await server.db.fetchDistinctIdValues(person)).toEqual(['distinct_id'])
        expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })
    })

    test('any event can do $set_once on props', async () => {
        await createPerson(server, team, ['distinct_id'])

        await processEvent(
            'distinct_id',
            '',
            '',
            ({
                event: 'some_event',
                properties: {
                    token: team.api_token,
                    distinct_id: 'distinct_id',
                    $set_once: { a_prop: 'test-1', c_prop: 'test-1' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )

        expect((await server.db.fetchEvents()).length).toBe(1)

        const [event] = await server.db.fetchEvents()
        expect(event.properties['$set_once']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

        const [person] = await server.db.fetchPersons()
        expect(await server.db.fetchDistinctIdValues(person)).toEqual(['distinct_id'])
        expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

        await processEvent(
            'distinct_id',
            '',
            '',
            ({
                event: 'some_other_event',
                properties: {
                    token: team.api_token,
                    distinct_id: 'distinct_id',
                    $set_once: { a_prop: 'test-2', b_prop: 'test-2b' },
                },
            } as any) as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
        expect((await server.db.fetchEvents()).length).toBe(2)
        const [person2] = await server.db.fetchPersons()
        expect(person2.properties).toEqual({ a_prop: 'test-1', b_prop: 'test-2b', c_prop: 'test-1' })
    })

    return returned
}
