import ClickHouse from '@posthog/clickhouse'
import { Properties } from '@posthog/plugin-scaffold'
import { Producer } from 'kafkajs'
import { DateTime } from 'luxon'
import { Pool, QueryConfig, QueryResult, QueryResultRow } from 'pg'

import { KAFKA_PERSON, KAFKA_PERSON_UNIQUE_ID } from './ingestion/topics'
import { chainToElements, hashElements, unparsePersonPartial } from './ingestion/utils'
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
    PostgresSessionRecordingEvent,
    RawOrganization,
    RawPerson,
    SessionRecordingEvent,
    TimestampFormat,
} from './types'
import { castTimestampOrNow, clickHouseTimestampToISO, escapeClickHouseString, sanitizeSqlIdentifier } from './utils'

/** The recommended way of accessing the database. */
export class DB {
    /** Postgres connection pool for primary database access. */
    postgres: Pool
    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    kafkaProducer?: Producer
    /** ClickHouse used for syncing Postgres and ClickHouse person data. */
    clickhouse?: ClickHouse

    constructor(postgres: Pool, kafkaProducer?: Producer, clickhouse?: ClickHouse) {
        this.postgres = postgres
        this.kafkaProducer = kafkaProducer
        this.clickhouse = clickhouse
    }

    // Direct queries

    public async postgresQuery<R extends QueryResultRow = any, I extends any[] = any[]>(
        queryTextOrConfig: string | QueryConfig<I>,
        values?: I
    ): Promise<QueryResult<R>> {
        return await this.postgres.query(queryTextOrConfig, values)
    }

    public async clickhouseQuery(
        query: string,
        options?: ClickHouse.QueryOptions
    ): Promise<ClickHouse.QueryResult<Record<string, any>>> {
        if (!this.clickhouse) {
            throw new Error('ClickHouse connection has not been provided to this DB instance!')
        }
        return await this.clickhouse.querying(query, options)
    }

    // Person

    public async fetchPersons(database?: Database.Postgres): Promise<Person[]>
    public async fetchPersons(database: Database.ClickHouse): Promise<ClickHousePerson[]>
    public async fetchPersons(database: Database = Database.Postgres): Promise<Person[] | ClickHousePerson[]> {
        if (database === Database.ClickHouse) {
            return (await this.clickhouseQuery('SELECT * FROM person')).data as ClickHousePerson[]
        } else if (database === Database.Postgres) {
            return ((await this.postgresQuery('SELECT * FROM posthog_person')).rows as RawPerson[]).map(
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
            [teamId, distinctId]
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
        const insertResult = await this.postgresQuery(
            'INSERT INTO posthog_person (created_at, properties, team_id, is_user_id, is_identified, uuid) VALUES ($1, $2, $3, $4, $5, $6) RETURNING *',
            [createdAt.toISO(), JSON.stringify(properties), teamId, isUserId, isIdentified, uuid]
        )
        const personCreated = insertResult.rows[0] as RawPerson
        const person = { ...personCreated, created_at: DateTime.fromISO(personCreated.created_at).toUTC() } as Person
        if (this.kafkaProducer) {
            const data = {
                created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouse),
                properties: JSON.stringify(properties),
                team_id: teamId,
                is_identified: isIdentified,
                id: uuid,
            }
            await this.kafkaProducer.send({
                topic: KAFKA_PERSON,
                messages: [{ value: Buffer.from(JSON.stringify(data)) }],
            })
        }

        for (const distinctId of distinctIds || []) {
            await this.addDistinctId(person, distinctId)
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
            values
        )
        if (this.clickhouse) {
            const { is_user_id, id, uuid, ...validUpdates } = update
            const updateString = Object.entries(validUpdates)
                .map(([key, value]) => {
                    let clickhouseValue: string
                    if (typeof value === 'string') {
                        clickhouseValue = value
                    } else if (typeof value === 'boolean') {
                        clickhouseValue = value ? '1' : '0'
                    } else if (DateTime.isDateTime(value)) {
                        clickhouseValue = castTimestampOrNow(value, TimestampFormat.ClickHouseSecondPrecision)
                    } else {
                        clickhouseValue = JSON.stringify(value)
                    }
                    return `${sanitizeSqlIdentifier(key)} = '${escapeClickHouseString(clickhouseValue)}'`
                })
                .join(', ')
            if (updateString.length > 0) {
                await this.clickhouseQuery(
                    `ALTER TABLE person UPDATE ${updateString} WHERE id = '${escapeClickHouseString(person.uuid)}'`
                )
            }
        }
        return updatedPerson
    }

    public async deletePerson(person: Person): Promise<void> {
        await this.postgresQuery('DELETE FROM posthog_persondistinctid WHERE person_id = $1', [person.id])
        await this.postgresQuery('DELETE FROM posthog_person WHERE id = $1', [person.id])
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
                [person.id, person.team_id]
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
        const insertResult = await this.postgresQuery(
            'INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id) VALUES ($1, $2, $3) RETURNING *',
            [distinctId, person.id, person.team_id]
        )
        const personDistinctIdCreated = insertResult.rows[0] as PersonDistinctId
        if (this.kafkaProducer) {
            await this.kafkaProducer.send({
                topic: KAFKA_PERSON_UNIQUE_ID,
                messages: [
                    { value: Buffer.from(JSON.stringify({ ...personDistinctIdCreated, person_id: person.uuid })) },
                ],
            })
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
            await this.kafkaProducer.send({
                topic: KAFKA_PERSON_UNIQUE_ID,
                messages: [{ value: Buffer.from(JSON.stringify(clickhouseModel)) }],
            })
        }
    }

    // Organization

    public async fetchOrganization(organizationId: string): Promise<RawOrganization | undefined> {
        const selectResult = await this.postgresQuery(`SELECT * FROM posthog_organization WHERE id $1`, [
            organizationId,
        ])
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
            const insertResult = await this.postgresQuery(
                'INSERT INTO posthog_elementgroup (hash, team_id) VALUES ($1, $2) RETURNING *',
                [hash, teamId]
            )
            const elementGroup = insertResult.rows[0] as ElementGroup
            for (const element of cleanedElements) {
                await this.postgresQuery(
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
        } catch (error) {
            // Throw further if not postgres error nr "23505" == "unique_violation"
            // https://www.postgresql.org/docs/12/errcodes-appendix.html
            if (error.code !== '23505') {
                throw error
            }
        }

        return hash
    }
}
