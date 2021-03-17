import ClickHouse from '@posthog/clickhouse'
import { CacheOptions, Properties } from '@posthog/plugin-scaffold'
import { Pool as GenericPool } from 'generic-pool'
import { StatsD, Tags } from 'hot-shots'
import Redis from 'ioredis'
import { Producer, ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { Pool, PoolClient, QueryConfig, QueryResult, QueryResultRow } from 'pg'

import { KAFKA_PERSON, KAFKA_PERSON_UNIQUE_ID } from './ingestion/topics'
import { chainToElements, hashElements, timeoutGuard, unparsePersonPartial } from './ingestion/utils'
import {
    ClickHouseEvent,
    ClickHousePerson,
    ClickHousePersonDistinctId,
    Database,
    Element,
    ElementGroup,
    Event,
    Person,
    PersonDistinctId,
    PluginsServerConfig,
    PostgresSessionRecordingEvent,
    RawOrganization,
    RawPerson,
    SessionRecordingEvent,
    TimestampFormat,
} from './types'
import {
    castTimestampOrNow,
    clickHouseTimestampToISO,
    createRedis,
    escapeClickHouseString,
    sanitizeSqlIdentifier,
    tryTwice,
} from './utils'

/** The recommended way of accessing the database. */
export class DB {
    /** Postgres connection pool for primary database access. */
    postgres: Pool
    /** Redis used for various caches. */
    redisPool: GenericPool<Redis.Redis>

    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    kafkaProducer?: Producer
    /** ClickHouse used for syncing Postgres and ClickHouse person data. */
    clickhouse?: ClickHouse

    /** StatsD instance used to do instrumentation */
    statsd: StatsD | undefined

    /** Queued producer for kafka */
    lastFlushTime: Date
    kafkaMessageQueue: Array<ProducerRecord>
    kafkaFlushInterval: NodeJS.Timeout
    flushFrequencyMs: number
    maxQueueSize: number

    constructor(
        postgres: Pool,
        redisPool: GenericPool<Redis.Redis>,
        kafkaProducer: Producer | undefined,
        clickhouse: ClickHouse | undefined,
        statsd: StatsD | undefined,
        serverConfig: PluginsServerConfig
    ) {
        this.postgres = postgres
        this.redisPool = redisPool
        this.kafkaProducer = kafkaProducer
        this.clickhouse = clickhouse
        this.statsd = statsd

        this.lastFlushTime = new Date()
        this.kafkaMessageQueue = []
        this.flushFrequencyMs = serverConfig.KAFKA_FLUSH_FREQUENCY_MS
        this.maxQueueSize = serverConfig.KAFKA_PRODUCER_MAX_QUEUE_SIZE
        this.kafkaFlushInterval = setInterval(() => this.flushKafkaMessages(), this.flushFrequencyMs)
    }

    // Postgres

    public async postgresQuery<R extends QueryResultRow = any, I extends any[] = any[]>(
        queryTextOrConfig: string | QueryConfig<I>,
        values?: I,
        tag?: string
    ): Promise<QueryResult<R>> {
        return this.instrumentQuery('query.postgres', tag, async () => {
            const timeout = timeoutGuard(`Postgres slow query warning after 30 sec: ${queryTextOrConfig}`)
            try {
                return await this.postgres.query(queryTextOrConfig, values)
            } finally {
                clearTimeout(timeout)
            }
        })
    }

    public async postgresTransaction<ReturnType extends any>(
        transaction: (client: PoolClient) => Promise<ReturnType>
    ): Promise<ReturnType> {
        return this.instrumentQuery('query.postgres_transation', undefined, async () => {
            const timeout = timeoutGuard(`Postgres slow transaction warning after 30 sec!`)
            const client = await this.postgres.connect()
            try {
                await client.query('BEGIN')
                const response = await transaction(client)
                await client.query('COMMIT')
                return response
            } catch (e) {
                await client.query('ROLLBACK')
                throw e
            } finally {
                client.release()
                clearTimeout(timeout)
            }
        })
    }

    // ClickHouse

    public async clickhouseQuery(
        query: string,
        options?: ClickHouse.QueryOptions
    ): Promise<ClickHouse.QueryResult<Record<string, any>>> {
        return this.instrumentQuery('query.clickhouse', undefined, async () => {
            if (!this.clickhouse) {
                throw new Error('ClickHouse connection has not been provided to this DB instance!')
            }
            const timeout = timeoutGuard(`ClickHouse slow query warning after 30 sec: ${query}`)
            try {
                return await this.clickhouse.querying(query, options)
            } finally {
                clearTimeout(timeout)
            }
        })
    }

    // Kafka
    public async queueKafkaMessage(kafkaMessage: ProducerRecord): Promise<void> {
        this.kafkaMessageQueue.push(kafkaMessage)

        const timeSinceLastFlush = new Date().getTime() - this.lastFlushTime.getTime()
        if (timeSinceLastFlush > this.flushFrequencyMs || this.kafkaMessageQueue.length >= this.maxQueueSize) {
            await this.flushKafkaMessages()
        }
    }

    public async flushKafkaMessages(): Promise<void> {
        if (this.kafkaMessageQueue.length === 0) {
            return
        }

        return this.instrumentQuery('query.kafka_send', undefined, async () => {
            if (!this.kafkaProducer) {
                throw new Error('Kafka connection has not been provided!')
            }

            const batches: Record<string, ProducerRecord> = {}
            for (const { topic, messages } of this.kafkaMessageQueue) {
                if (!batches[topic]) {
                    batches[topic] = {
                        topic,
                        messages: [],
                    }
                }
                batches[topic].messages = batches[topic].messages.concat(messages)
            }

            this.kafkaMessageQueue = []
            this.lastFlushTime = new Date()

            const timeout = timeoutGuard(`Kafka message sending delayed. Waiting over 30 sec to send messages.`)
            try {
                await this.kafkaProducer!.sendBatch({
                    topicMessages: Object.values(batches),
                })
            } finally {
                clearTimeout(timeout)
            }
        })
    }

    // Redis

    public async redisGet(key: string, defaultValue: unknown, options: CacheOptions = {}): Promise<unknown> {
        const { jsonSerialize = true } = options

        return this.instrumentQuery('query.regisGet', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard(`Getting redis key delayed. Waiting over 30 sec to get key: ${key}`)
            try {
                const value = await tryTwice(
                    async () => await client.get(key),
                    `Waited 5 sec to get redis key: ${key}, retrying once!`
                )
                if (typeof value === 'undefined') {
                    return defaultValue
                }
                return value ? (jsonSerialize ? JSON.parse(value) : value) : null
            } catch (error) {
                if (error instanceof SyntaxError) {
                    // invalid JSON
                    return null
                } else {
                    throw error
                }
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public async redisSet(key: string, value: unknown, ttlSeconds?: number, options: CacheOptions = {}): Promise<void> {
        const { jsonSerialize = true } = options

        return this.instrumentQuery('query.redisSet', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard(`Setting redis key delayed. Waiting over 30 sec to set key: ${key}`)
            try {
                const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string)
                if (ttlSeconds) {
                    await client.set(key, serializedValue, 'EX', ttlSeconds)
                } else {
                    await client.set(key, serializedValue)
                }
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public async redisIncr(key: string): Promise<number> {
        return this.instrumentQuery('query.redisIncr', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard(`Incrementing redis key delayed. Waiting over 30 sec to incr key: ${key}`)
            try {
                return await client.incr(key)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public async redisExpire(key: string, ttlSeconds: number): Promise<boolean> {
        return this.instrumentQuery('query.redisExpire', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard(`Expiring redis key delayed. Waiting over 30 sec to expire key: ${key}`)
            try {
                return (await client.expire(key, ttlSeconds)) === 1
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public async redisLPush(key: string, value: unknown, options: CacheOptions = {}): Promise<number> {
        const { jsonSerialize = true } = options

        return this.instrumentQuery('query.redisLPush', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard(`LPushing redis key delayed. Waiting over 30 sec to lpush key: ${key}`)
            try {
                const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string)
                return await client.lpush(key, serializedValue)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public async redisBRPop(key1: string, key2: string): Promise<[string, string]> {
        return this.instrumentQuery('query.redisBRPop', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard(
                `BRPoping redis key delayed. Waiting over 30 sec to brpop keys: ${key1}, ${key2}`
            )
            try {
                return await client.brpop(key1, key2)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    // Person

    public async fetchPersons(database?: Database.Postgres): Promise<Person[]>
    public async fetchPersons(database: Database.ClickHouse): Promise<ClickHousePerson[]>
    public async fetchPersons(database: Database = Database.Postgres): Promise<Person[] | ClickHousePerson[]> {
        if (database === Database.ClickHouse) {
            const query = `
                SELECT * FROM person JOIN (
                    SELECT id, max(_timestamp) as _timestamp FROM person GROUP BY team_id, id
                ) as person_max ON person.id = person_max.id AND person._timestamp = person_max._timestamp
            `
            return (await this.clickhouseQuery(query)).data.map((row) => {
                const { 'person_max._timestamp': _discard1, 'person_max.id': _discard2, ...rest } = row
                return rest
            }) as ClickHousePerson[]
        } else if (database === Database.Postgres) {
            return ((await this.postgresQuery('SELECT * FROM posthog_person', undefined, 'fetchPersons'))
                .rows as RawPerson[]).map(
                (rawPerson: RawPerson) =>
                    ({
                        ...rawPerson,
                        created_at: DateTime.fromISO(rawPerson.created_at).toUTC(),
                    } as Person)
            )
        } else {
            throw new Error(`Can't fetch persons for database: ${database}`)
        }
    }

    public async fetchPerson(teamId: number, distinctId: string): Promise<Person | undefined> {
        const selectResult = await this.postgresQuery(
            `SELECT
                posthog_person.id, posthog_person.created_at, posthog_person.team_id, posthog_person.properties,
                posthog_person.is_user_id, posthog_person.is_identified, posthog_person.uuid,
                posthog_persondistinctid.team_id AS persondistinctid__team_id,
                posthog_persondistinctid.distinct_id AS persondistinctid__distinct_id
            FROM posthog_person
            JOIN posthog_persondistinctid ON (posthog_persondistinctid.person_id = posthog_person.id)
            WHERE
                posthog_person.team_id = $1
                AND posthog_persondistinctid.team_id = $1
                AND posthog_persondistinctid.distinct_id = $2`,
            [teamId, distinctId],
            'fetchPerson'
        )
        if (selectResult.rows.length > 0) {
            const rawPerson: RawPerson = selectResult.rows[0]
            return { ...rawPerson, created_at: DateTime.fromISO(rawPerson.created_at).toUTC() }
        }
    }

    public async createPerson(
        createdAt: DateTime,
        properties: Properties,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        distinctIds?: string[]
    ): Promise<Person> {
        const kafkaMessages: ProducerRecord[] = []

        const person = await this.postgresTransaction(async (client) => {
            const insertResult = await client.query(
                'INSERT INTO posthog_person (created_at, properties, team_id, is_user_id, is_identified, uuid) VALUES ($1, $2, $3, $4, $5, $6) RETURNING *',
                [createdAt.toISO(), JSON.stringify(properties), teamId, isUserId, isIdentified, uuid]
            )
            const personCreated = insertResult.rows[0] as RawPerson
            const person = {
                ...personCreated,
                created_at: DateTime.fromISO(personCreated.created_at).toUTC(),
            } as Person

            if (this.kafkaProducer) {
                kafkaMessages.push({
                    topic: KAFKA_PERSON,
                    messages: [
                        {
                            value: Buffer.from(
                                JSON.stringify({
                                    created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouse),
                                    properties: JSON.stringify(properties),
                                    team_id: teamId,
                                    is_identified: isIdentified,
                                    id: uuid,
                                })
                            ),
                        },
                    ],
                })
            }

            for (const distinctId of distinctIds || []) {
                const kafkaMessage = await this.addDistinctIdPooled(client, person, distinctId)
                if (kafkaMessage) {
                    kafkaMessages.push(kafkaMessage)
                }
            }

            return person
        })

        if (this.kafkaProducer) {
            for (const kafkaMessage of kafkaMessages) {
                await this.queueKafkaMessage(kafkaMessage)
            }
        }

        return person
    }

    public async updatePerson(person: Person, update: Partial<Person>): Promise<Person> {
        const updatedPerson: Person = { ...person, ...update }
        const values = [...Object.values(unparsePersonPartial(update)), person.id]
        await this.postgresQuery(
            `UPDATE posthog_person SET ${Object.keys(update).map(
                (field, index) => `"${sanitizeSqlIdentifier(field)}" = $${index + 1}`
            )} WHERE id = $${Object.values(update).length + 1}`,
            values,
            'updatePerson'
        )

        if (this.kafkaProducer) {
            await this.queueKafkaMessage({
                topic: KAFKA_PERSON,
                messages: [
                    {
                        value: Buffer.from(
                            JSON.stringify({
                                created_at: castTimestampOrNow(
                                    updatedPerson.created_at,
                                    TimestampFormat.ClickHouseSecondPrecision
                                ),
                                properties: JSON.stringify(updatedPerson.properties),
                                team_id: updatedPerson.team_id,
                                is_identified: updatedPerson.is_identified,
                                id: updatedPerson.uuid,
                            })
                        ),
                    },
                ],
            })
        }

        return updatedPerson
    }

    public async deletePerson(person: Person): Promise<void> {
        await this.postgresTransaction(async (client) => {
            await client.query('DELETE FROM posthog_persondistinctid WHERE person_id = $1', [person.id])
            await client.query('DELETE FROM posthog_person WHERE id = $1', [person.id])
        })
        if (this.clickhouse) {
            await this.clickhouseQuery(`ALTER TABLE person DELETE WHERE id = '${escapeClickHouseString(person.uuid)}'`)
            await this.clickhouseQuery(
                `ALTER TABLE person_distinct_id DELETE WHERE person_id = '${escapeClickHouseString(person.uuid)}'`
            )
        }
    }

    // PersonDistinctId

    public async fetchDistinctIds(person: Person, database?: Database.Postgres): Promise<PersonDistinctId[]>
    public async fetchDistinctIds(person: Person, database: Database.ClickHouse): Promise<ClickHousePersonDistinctId[]>
    public async fetchDistinctIds(
        person: Person,
        database: Database = Database.Postgres
    ): Promise<PersonDistinctId[] | ClickHousePersonDistinctId[]> {
        if (database === Database.ClickHouse) {
            return (
                await this.clickhouseQuery(
                    `SELECT * FROM person_distinct_id WHERE person_id='${escapeClickHouseString(
                        person.uuid
                    )}' and team_id='${person.team_id}' ORDER BY id`
                )
            ).data as ClickHousePersonDistinctId[]
        } else if (database === Database.Postgres) {
            const result = await this.postgresQuery(
                'SELECT * FROM posthog_persondistinctid WHERE person_id=$1 and team_id=$2 ORDER BY id',
                [person.id, person.team_id],
                'fetchDistinctIds'
            )
            return result.rows as PersonDistinctId[]
        } else {
            throw new Error(`Can't fetch persons for database: ${database}`)
        }
    }

    public async fetchDistinctIdValues(person: Person, database: Database = Database.Postgres): Promise<string[]> {
        const personDistinctIds = await this.fetchDistinctIds(person, database as any)
        return personDistinctIds.map((pdi) => pdi.distinct_id)
    }

    public async addDistinctId(person: Person, distinctId: string): Promise<void> {
        const kafkaMessage = await this.addDistinctIdPooled(this.postgres, person, distinctId)
        if (this.kafkaProducer && kafkaMessage) {
            await this.queueKafkaMessage(kafkaMessage)
        }
    }

    public async addDistinctIdPooled(
        client: PoolClient | Pool,
        person: Person,
        distinctId: string
    ): Promise<ProducerRecord | void> {
        const insertResult = await client.query(
            'INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id) VALUES ($1, $2, $3) RETURNING *',
            [distinctId, person.id, person.team_id]
        )

        const personDistinctIdCreated = insertResult.rows[0] as PersonDistinctId
        if (this.kafkaProducer) {
            return {
                topic: KAFKA_PERSON_UNIQUE_ID,
                messages: [
                    { value: Buffer.from(JSON.stringify({ ...personDistinctIdCreated, person_id: person.uuid })) },
                ],
            }
        }
    }

    public async moveDistinctId(
        person: Person,
        personDistinctId: PersonDistinctId,
        moveToPerson: Person
    ): Promise<void> {
        await this.postgresQuery(`UPDATE posthog_persondistinctid SET person_id = $1 WHERE id = $2`, [
            moveToPerson.id,
            personDistinctId.id,
        ])
        if (this.kafkaProducer) {
            const clickhouseModel: ClickHousePersonDistinctId = { ...personDistinctId, person_id: moveToPerson.uuid }
            await this.queueKafkaMessage({
                topic: KAFKA_PERSON_UNIQUE_ID,
                messages: [{ value: Buffer.from(JSON.stringify(clickhouseModel)) }],
            })
        }
    }

    // Organization

    public async fetchOrganization(organizationId: string): Promise<RawOrganization | undefined> {
        const selectResult = await this.postgresQuery(
            `SELECT * FROM posthog_organization WHERE id $1`,
            [organizationId],
            'fetchOrganization'
        )
        const rawOrganization: RawOrganization = selectResult.rows[0]
        return rawOrganization
    }

    // Event

    public async fetchEvents(): Promise<Event[] | ClickHouseEvent[]> {
        if (this.kafkaProducer) {
            const events = (await this.clickhouseQuery(`SELECT * FROM events`)).data as ClickHouseEvent[]
            return (
                events?.map(
                    (event) =>
                        ({
                            ...event,
                            ...(typeof event['properties'] === 'string'
                                ? { properties: JSON.parse(event.properties) }
                                : {}),
                            timestamp: clickHouseTimestampToISO(event.timestamp),
                        } as ClickHouseEvent)
                ) || []
            )
        } else {
            const result = await this.postgresQuery('SELECT * FROM posthog_event')
            return result.rows as Event[]
        }
    }

    // SessionRecordingEvent

    public async fetchSessionRecordingEvents(): Promise<PostgresSessionRecordingEvent[] | SessionRecordingEvent[]> {
        if (this.kafkaProducer) {
            const events = ((await this.clickhouseQuery(`SELECT * FROM session_recording_events`))
                .data as SessionRecordingEvent[]).map((event) => {
                return {
                    ...event,
                    snapshot_data: event.snapshot_data ? JSON.parse(event.snapshot_data) : null,
                }
            })
            return events
        } else {
            const result = await this.postgresQuery('SELECT * FROM posthog_sessionrecordingevent')
            return result.rows as PostgresSessionRecordingEvent[]
        }
    }

    // Element

    public async fetchElements(event?: Event): Promise<Element[]> {
        if (this.kafkaProducer) {
            const events = (
                await this.clickhouseQuery(
                    `SELECT elements_chain FROM events WHERE uuid='${escapeClickHouseString((event as any).uuid)}'`
                )
            ).data as ClickHouseEvent[]
            const chain = events?.[0]?.elements_chain
            return chainToElements(chain)
        } else {
            return (await this.postgresQuery('SELECT * FROM posthog_element')).rows
        }
    }

    public async createElementGroup(elements: Element[], teamId: number): Promise<string> {
        const cleanedElements = elements.map((element, index) => ({ ...element, order: index }))
        const hash = hashElements(cleanedElements)

        try {
            await this.postgresTransaction(async (client) => {
                const insertResult = await client.query(
                    'INSERT INTO posthog_elementgroup (hash, team_id) VALUES ($1, $2) RETURNING *',
                    [hash, teamId]
                )
                const elementGroup = insertResult.rows[0] as ElementGroup
                for (const element of cleanedElements) {
                    await client.query(
                        'INSERT INTO posthog_element (text, tag_name, href, attr_id, nth_child, nth_of_type, attributes, "order", event_id, attr_class, group_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)',
                        [
                            element.text,
                            element.tag_name,
                            element.href,
                            element.attr_id,
                            element.nth_child,
                            element.nth_of_type,
                            element.attributes || '{}',
                            element.order,
                            element.event_id,
                            element.attr_class,
                            elementGroup.id,
                        ]
                    )
                }
            })
        } catch (error) {
            // Throw further if not postgres error nr "23505" == "unique_violation"
            // https://www.postgresql.org/docs/12/errcodes-appendix.html
            if (error.code !== '23505') {
                throw error
            }
        }

        return hash
    }

    private async instrumentQuery<T>(
        metricName: string,
        tag: string | undefined,
        runQuery: () => Promise<T>
    ): Promise<T> {
        const tags: Tags | undefined = tag ? { queryTag: tag } : undefined
        const timer = new Date()

        this.statsd?.increment(`${metricName}.total`, tags)
        try {
            return await runQuery()
        } finally {
            this.statsd?.timing(metricName, timer, tags)
        }
    }
}
