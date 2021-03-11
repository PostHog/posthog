import ClickHouse from '@posthog/clickhouse'
import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import equal from 'fast-deep-equal'
import { Producer } from 'kafkajs'
import { DateTime, Duration } from 'luxon'
import * as fetch from 'node-fetch'
import { nodePostHog } from 'posthog-js-lite/dist/src/targets/node'

import Client from '../celery/client'
import { DB } from '../db'
import { Event as EventProto, IEvent } from '../idl/protos'
import { status } from '../status'
import {
    CohortPeople,
    Element,
    Person,
    PersonDistinctId,
    PluginsServer,
    PostgresSessionRecordingEvent,
    SessionRecordingEvent,
    Team,
    TimestampFormat,
} from '../types'
import { castTimestampOrNow, UUID, UUIDT } from '../utils'
import { KAFKA_EVENTS, KAFKA_SESSION_RECORDING_EVENTS } from './topics'
import { elementsToString, personInitialAndUTMProperties, sanitizeEventName, timeoutGuard } from './utils'

export class EventsProcessor {
    pluginsServer: PluginsServer
    db: DB
    clickhouse: ClickHouse
    kafkaProducer: Producer
    celery: Client
    posthog: ReturnType<typeof nodePostHog>

    constructor(pluginsServer: PluginsServer) {
        this.pluginsServer = pluginsServer
        this.db = pluginsServer.db
        this.clickhouse = pluginsServer.clickhouse!
        this.kafkaProducer = pluginsServer.kafkaProducer!
        this.celery = new Client(pluginsServer.db, pluginsServer.CELERY_DEFAULT_QUEUE)
        this.posthog = nodePostHog('sTMFPsFhdP1Ssg', { fetch })
        if (process.env.NODE_ENV === 'test') {
            this.posthog.optOut()
        }
    }

    public async processEvent(
        distinctId: string,
        ip: string | null,
        siteUrl: string,
        data: PluginEvent,
        teamId: number,
        now: DateTime,
        sentAt: DateTime | null,
        eventUuid: string
    ): Promise<IEvent | SessionRecordingEvent> {
        if (!UUID.validateString(eventUuid, false)) {
            throw new Error(`Not a valid UUID: "${eventUuid}"`)
        }
        const singleSaveTimer = new Date()
        const timeout = timeoutGuard(
            `Still inside "EventsProcessor.processEvent". Timeout warning after 30 sec! ${JSON.stringify(data)}`
        )

        const properties: Properties = data.properties ?? {}
        if (data['$set']) {
            properties['$set'] = data['$set']
        }
        if (data['$set_once']) {
            properties['$set_once'] = data['$set_once']
        }

        const personUuid = new UUIDT().toString()

        const ts = this.handleTimestamp(data, now, sentAt)
        const timeout1 = timeoutGuard(
            `Still running "handleIdentifyOrAlias". Timeout warning after 30 sec! ${eventUuid}`
        )
        await this.handleIdentifyOrAlias(data['event'], properties, distinctId, teamId)
        clearTimeout(timeout1)

        let result: IEvent | SessionRecordingEvent

        if (data['event'] === '$snapshot') {
            const timeout2 = timeoutGuard(
                `Still running "createSessionRecordingEvent". Timeout warning after 30 sec! ${eventUuid}`
            )
            result = await this.createSessionRecordingEvent(
                eventUuid,
                teamId,
                distinctId,
                properties['$session_id'],
                ts,
                properties['$snapshot_data']
            )
            this.pluginsServer.statsd?.timing('kafka_queue.single_save.snapshot', singleSaveTimer)
            clearTimeout(timeout2)
        } else {
            const timeout3 = timeoutGuard(`Still running "captureEE". Timeout warning after 30 sec! ${eventUuid}`)
            result = await this.captureEE(
                eventUuid,
                personUuid,
                ip,
                siteUrl,
                teamId,
                data['event'],
                distinctId,
                properties,
                ts,
                sentAt
            )
            this.pluginsServer.statsd?.timing('kafka_queue.single_save.standard', singleSaveTimer)
            clearTimeout(timeout3)
        }
        clearTimeout(timeout)

        return result
    }

    private handleTimestamp(data: PluginEvent, now: DateTime, sentAt: DateTime | null): DateTime {
        if (data['timestamp']) {
            if (sentAt) {
                // sent_at - timestamp == now - x
                // x = now + (timestamp - sent_at)
                try {
                    // timestamp and sent_at must both be in the same format: either both with or both without timezones
                    // otherwise we can't get a diff to add to now
                    return now.plus(DateTime.fromISO(data['timestamp']).diff(sentAt))
                } catch (error) {
                    status.error('⚠️', 'Error when handling timestamp:', error)
                    Sentry.captureException(error)
                }
            }
            return DateTime.fromISO(data['timestamp'])
        }
        if (data['offset']) {
            return now.minus(Duration.fromMillis(data['offset']))
        }
        return now
    }

    private async handleIdentifyOrAlias(
        event: string,
        properties: Properties,
        distinctId: string,
        teamId: number
    ): Promise<void> {
        if (event === '$create_alias') {
            await this.alias(properties['alias'], distinctId, teamId)
        } else if (event === '$identify') {
            if (properties['$anon_distinct_id']) {
                await this.alias(properties['$anon_distinct_id'], distinctId, teamId)
            }
            await this.setIsIdentified(teamId, distinctId)
        }
    }

    private async setIsIdentified(teamId: number, distinctId: string, isIdentified = true): Promise<void> {
        let personFound = await this.db.fetchPerson(teamId, distinctId)
        if (!personFound) {
            try {
                personFound = await this.db.createPerson(
                    DateTime.utc(),
                    {},
                    teamId,
                    null,
                    true,
                    new UUIDT().toString(),
                    [distinctId]
                )
            } catch {
                // Catch race condition where in between getting and creating,
                // another request already created this person
                personFound = await this.db.fetchPerson(teamId, distinctId)
            }
        }
        if (personFound && !personFound.is_identified) {
            await this.db.updatePerson(personFound, { is_identified: isIdentified })
        }
    }

    private async updatePersonProperties(
        teamId: number,
        distinctId: string,
        properties: Properties,
        propertiesOnce: Properties
    ): Promise<Person> {
        let personFound = await this.db.fetchPerson(teamId, distinctId)
        if (!personFound) {
            try {
                personFound = await this.db.createPerson(
                    DateTime.utc(),
                    properties,
                    teamId,
                    null,
                    false,
                    new UUIDT().toString(),
                    [distinctId]
                )
            } catch {
                // Catch race condition where in between getting and creating,
                // another request already created this person
                personFound = await this.db.fetchPerson(teamId, distinctId)
            }
        }
        if (!personFound) {
            throw new Error(
                `Could not find person with distinct id "${distinctId}" in team "${teamId}", even after trying to insert them`
            )
        }
        const updatedProperties: Properties = { ...propertiesOnce, ...personFound.properties, ...properties }

        if (equal(personFound.properties, updatedProperties)) {
            return personFound
        }

        return await this.db.updatePerson(personFound, { properties: updatedProperties })
    }

    private async alias(
        previousDistinctId: string,
        distinctId: string,
        teamId: number,
        retryIfFailed = true
    ): Promise<void> {
        const oldPerson = await this.db.fetchPerson(teamId, previousDistinctId)
        const newPerson = await this.db.fetchPerson(teamId, distinctId)

        if (oldPerson && !newPerson) {
            try {
                await this.db.addDistinctId(oldPerson, distinctId)
                // Catch race case when somebody already added this distinct_id between .get and .addDistinctId
            } catch {
                // integrity error
                if (retryIfFailed) {
                    // run everything again to merge the users if needed
                    await this.alias(previousDistinctId, distinctId, teamId, false)
                }
            }
            return
        }

        if (!oldPerson && newPerson) {
            try {
                await this.db.addDistinctId(newPerson, previousDistinctId)
                // Catch race case when somebody already added this distinct_id between .get and .addDistinctId
            } catch {
                // integrity error
                if (retryIfFailed) {
                    // run everything again to merge the users if needed
                    await this.alias(previousDistinctId, distinctId, teamId, false)
                }
            }
            return
        }

        if (!oldPerson && !newPerson) {
            try {
                await this.db.createPerson(DateTime.utc(), {}, teamId, null, false, new UUIDT().toString(), [
                    distinctId,
                    previousDistinctId,
                ])
            } catch {
                // Catch race condition where in between getting and creating,
                // another request already created this person
                if (retryIfFailed) {
                    // Try once more, probably one of the two persons exists now
                    await this.alias(previousDistinctId, distinctId, teamId, false)
                }
            }
            return
        }

        if (oldPerson && newPerson && oldPerson.id !== newPerson.id) {
            await this.mergePeople(newPerson, [oldPerson])
        }
    }

    public async mergePeople(mergeInto: Person, peopleToMerge: Person[]): Promise<void> {
        let firstSeen = mergeInto.created_at

        // merge the properties
        for (const otherPerson of peopleToMerge) {
            mergeInto.properties = { ...otherPerson.properties, ...mergeInto.properties }
            if (otherPerson.created_at < firstSeen) {
                // Keep the oldest created_at (i.e. the first time we've seen this person)
                firstSeen = otherPerson.created_at
            }
        }

        await this.db.updatePerson(mergeInto, { created_at: firstSeen, properties: mergeInto.properties })

        // merge the distinct_ids
        for (const otherPerson of peopleToMerge) {
            const otherPersonDistinctIds: PersonDistinctId[] = (
                await this.db.postgresQuery(
                    'SELECT * FROM posthog_persondistinctid WHERE person_id = $1 AND team_id = $2',
                    [otherPerson.id, mergeInto.team_id]
                )
            ).rows
            for (const personDistinctId of otherPersonDistinctIds) {
                await this.db.moveDistinctId(otherPerson, personDistinctId, mergeInto)
            }

            await this.db.postgresQuery('UPDATE posthog_cohortpeople SET person_id = $1 WHERE person_id = $2', [
                mergeInto.id,
                otherPerson.id,
            ])

            await this.db.deletePerson(otherPerson)
        }
    }

    private async captureEE(
        eventUuid: string,
        personUuid: string,
        ip: string | null,
        siteUrl: string,
        teamId: number,
        event: string,
        distinctId: string,
        properties: Properties,
        timestamp: DateTime,
        sentAt: DateTime | null
    ): Promise<IEvent> {
        event = sanitizeEventName(event)
        const elements: Record<string, any>[] | undefined = properties['$elements']
        let elementsList: Element[] = []
        if (elements && elements.length) {
            delete properties['$elements']
            elementsList = elements.map((el) => ({
                text: el['$el_text']?.slice(0, 400),
                tag_name: el['tag_name'],
                href: el['attr__href']?.slice(0, 2048),
                attr_class: el['attr__class']?.split(' '),
                attr_id: el['attr__id'],
                nth_child: el['nth_child'],
                nth_of_type: el['nth_of_type'],
                attributes: Object.fromEntries(Object.entries(el).filter(([key]) => key.startsWith('attr__'))),
            }))
        }

        const teamQueryResult = await this.db.postgresQuery('SELECT * FROM posthog_team WHERE id = $1', [teamId])
        const team: Team = teamQueryResult.rows[0]

        if (!team) {
            throw new Error(`No team found with ID ${teamId}. Can't ingest event.`)
        }

        if (ip && !team.anonymize_ips && !('$ip' in properties)) {
            properties['$ip'] = ip
        }

        await this.storeNamesAndProperties(team, event, properties)

        const pdiSelectResult = await this.db.postgresQuery(
            'SELECT COUNT(*) AS pdicount FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
            [teamId, distinctId]
        )
        const pdiCount = parseInt(pdiSelectResult.rows[0].pdicount)

        if (!pdiCount) {
            // Catch race condition where in between getting and creating, another request already created this user
            try {
                await this.db.createPerson(sentAt || DateTime.utc(), {}, teamId, null, false, personUuid.toString(), [
                    distinctId,
                ])
            } catch {}
        }

        properties = personInitialAndUTMProperties(properties)

        if (properties['$set'] || properties['$set_once']) {
            await this.updatePersonProperties(
                teamId,
                distinctId,
                properties['$set'] || {},
                properties['$set_once'] || {}
            )
        }

        return await this.createEvent(eventUuid, event, team, distinctId, properties, timestamp, elementsList, siteUrl)
    }

    private async storeNamesAndProperties(team: Team, event: string, properties: Properties): Promise<void> {
        const timeout = timeoutGuard(
            `Still running "storeNamesAndProperties". Timeout warning after 30 sec! Event: ${event}. Ingested: ${team.ingested_event}`
        )
        // In _capture we only prefetch a couple of fields in Team to avoid fetching too much data
        let save = false
        if (!team.ingested_event) {
            // First event for the team captured
            const organizationMembers = await this.db.postgresQuery(
                'SELECT distinct_id FROM posthog_user JOIN posthog_organizationmembership ON posthog_user.id = posthog_organizationmembership.user_id WHERE organization_id = $1',
                [team.organization_id]
            )
            const distinctIds: { distinct_id: string }[] = organizationMembers.rows
            for (const { distinct_id } of distinctIds) {
                this.posthog.identify(distinct_id)
                this.posthog.capture('first team event ingested', { team: team.uuid })
            }
            team.ingested_event = true
            save = true
        }
        if (team.event_names && !team.event_names.includes(event)) {
            save = true
            team.event_names.push(event)
            team.event_names_with_usage.push({ event: event, usage_count: null, volume: null })
        }
        for (const [key, value] of Object.entries(properties)) {
            if (team.event_properties && !team.event_properties.includes(key)) {
                team.event_properties.push(key)
                team.event_properties_with_usage.push({ key: key, usage_count: null, volume: null })
                save = true
            }
            if (
                typeof value === 'number' &&
                team.event_properties_numerical &&
                !team.event_properties_numerical.includes(key)
            ) {
                team.event_properties_numerical.push(key)
                save = true
            }
        }
        if (save) {
            const timeout2 = timeoutGuard(
                `Still running "storeNamesAndProperties" save. Timeout warning after 30 sec! Event: ${event}`
            )
            await this.db.postgresQuery(
                `UPDATE posthog_team SET
                    ingested_event = $1, event_names = $2, event_names_with_usage = $3, event_properties = $4,
                    event_properties_with_usage = $5, event_properties_numerical = $6
                WHERE id = $7`,
                [
                    team.ingested_event,
                    JSON.stringify(team.event_names),
                    JSON.stringify(team.event_names_with_usage),
                    JSON.stringify(team.event_properties),
                    JSON.stringify(team.event_properties_with_usage),
                    JSON.stringify(team.event_properties_numerical),
                    team.id,
                ]
            )
            clearTimeout(timeout2)
        }
        clearTimeout(timeout)
    }

    private async shouldSendHooksTask(team: Team): Promise<boolean> {
        // Webhooks
        if (team.slack_incoming_webhook) {
            return true
        }
        // REST hooks (Zapier)
        if (!this.pluginsServer.KAFKA_ENABLED) {
            // REST hooks are EE-only
            return false
        }
        const timeout = timeoutGuard(`Still running "shouldSendHooksTask". Timeout warning after 30 sec!`)
        try {
            const hookQueryResult = await this.db.postgresQuery(
                `SELECT COUNT(*) FROM ee_hook WHERE team_id = $1 AND event = 'action_performed' LIMIT 1`,
                [team.id]
            )
            return parseInt(hookQueryResult.rows[0].count) > 0
        } catch (error) {
            // In FOSS PostHog ee_hook does not exist. If the error is other than that, rethrow it
            if (!String(error).includes('relation "ee_hook" does not exist')) {
                throw error
            }
        } finally {
            clearTimeout(timeout)
        }
        return false
    }

    private async createEvent(
        uuid: string,
        event: string,
        team: Team,
        distinctId: string,
        properties?: Properties,
        timestamp?: DateTime | string,
        elements?: Element[],
        siteUrl?: string
    ): Promise<IEvent> {
        const timestampString = castTimestampOrNow(
            timestamp,
            this.kafkaProducer ? TimestampFormat.ClickHouse : TimestampFormat.ISO
        )
        const elementsChain = elements && elements.length ? elementsToString(elements) : ''

        const data: IEvent = {
            uuid,
            event,
            properties: JSON.stringify(properties ?? {}),
            timestamp: timestampString,
            teamId: team.id,
            distinctId,
            elementsChain,
            createdAt: timestampString,
        }

        if (this.kafkaProducer) {
            await this.db.sendKafkaMessage({
                topic: KAFKA_EVENTS,
                messages: [
                    {
                        key: uuid,
                        value: EventProto.encodeDelimited(EventProto.create(data)).finish() as Buffer,
                    },
                ],
            })
            if (await this.shouldSendHooksTask(team)) {
                this.pluginsServer.statsd?.increment(`hooks.send_task`)
                this.celery.sendTask(
                    'ee.tasks.webhooks_ee.post_event_to_webhook_ee',
                    [
                        {
                            event,
                            properties,
                            distinct_id: distinctId,
                            timestamp,
                            elements_chain: elementsChain,
                        },
                        team.id,
                        siteUrl,
                    ],
                    {}
                )
            }
        } else {
            let elementsHash = ''
            if (elements && elements.length > 0) {
                elementsHash = await this.db.createElementGroup(elements, team.id)
            }
            const {
                rows: [event],
            } = await this.db.postgresQuery(
                'INSERT INTO posthog_event (created_at, event, distinct_id, properties, team_id, timestamp, elements, elements_hash) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *',
                [
                    data.createdAt,
                    data.event,
                    distinctId,
                    data.properties,
                    data.teamId,
                    data.timestamp,
                    JSON.stringify(elements || []),
                    elementsHash,
                ]
            )
            if (await this.shouldSendHooksTask(team)) {
                this.pluginsServer.statsd?.increment(`hooks.send_task`)
                this.celery.sendTask('posthog.tasks.webhooks.post_event_to_webhook', [event.id, siteUrl], {})
            }
        }

        return data
    }

    private async createSessionRecordingEvent(
        uuid: string,
        team_id: number,
        distinct_id: string,
        session_id: string,
        timestamp: DateTime | string,
        snapshot_data: Record<any, any>
    ): Promise<SessionRecordingEvent | PostgresSessionRecordingEvent> {
        const timestampString = castTimestampOrNow(
            timestamp,
            this.kafkaProducer ? TimestampFormat.ClickHouse : TimestampFormat.ISO
        )

        const data: SessionRecordingEvent = {
            uuid,
            team_id: team_id,
            distinct_id: distinct_id,
            session_id: session_id,
            snapshot_data: JSON.stringify(snapshot_data),
            timestamp: timestampString,
            created_at: timestampString,
        }

        if (this.kafkaProducer) {
            await this.db.sendKafkaMessage({
                topic: KAFKA_SESSION_RECORDING_EVENTS,
                messages: [{ key: uuid, value: Buffer.from(JSON.stringify(data)) }],
            })
        } else {
            const insertResult = await this.db.postgresQuery(
                'INSERT INTO posthog_sessionrecordingevent (created_at, team_id, distinct_id, session_id, timestamp, snapshot_data) VALUES ($1, $2, $3, $4, $5, $6) RETURNING *',
                [data.created_at, data.team_id, data.distinct_id, data.session_id, data.timestamp, data.snapshot_data]
            )
            const eventCreated = insertResult.rows[0] as PostgresSessionRecordingEvent
            return eventCreated
        }
        return data
    }
}
