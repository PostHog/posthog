import { Kafka } from 'kafkajs'
import { PutObjectCommand } from '@aws-sdk/client-s3'
import { RecordingEvent, RecordingEventGroup } from '../types'
import { s3Client } from '../s3'
import { meterProvider } from './metrics'
import { performance } from 'perf_hooks'
import { getEventGroupDataString, getEventSummaryMetadata } from './utils'

const maxEventGroupAge = Number.parseInt(
    process.env.MAX_EVENT_GROUP_AGE || process.env.NODE_ENV === 'dev' ? '1000' : '300000'
)
const maxEventGroupSize = Number.parseInt(
    process.env.MAX_EVENT_GROUP_SIZE || process.env.NODE_ENV === 'dev' ? '1000' : '1000000'
)

const RECORDING_EVENTS_TOPIC = 'recording_events'

const kafka = new Kafka({
    clientId: 'ingester',
    brokers: ['localhost:9092'],
})

const consumer = kafka.consumer({
    groupId: `object-storage-ingester`,
})

consumer.connect()
consumer.subscribe({ topic: RECORDING_EVENTS_TOPIC })

const eventsBySessionId: { [key: string]: RecordingEventGroup } = {}

// Define the metrics we'll be exposing at /metrics
const meter = meterProvider.getMeter('ingester')
const messagesReceived = meter.createCounter('messages_received')
const snapshotMessagesProcessed = meter.createCounter('snapshot_messages_processed')
const eventGroupsCommittedCounter = meter.createCounter('event_groups_committed')
const eventGroupsStarted = meter.createCounter('event_groups_started')
const eventGroupsInFlight = meter.createObservableGauge('event_groups_in_flight', {
    description: "Number of event groups that haven't been committed to S3 yet.",
})
const s3PutObjectTime = meter.createHistogram('s3_put_object_time')

consumer.run({
    autoCommit: false,
    eachMessage: async ({ topic, partition, message }) => {
        // We need to parse the event to get team_id and session_id although
        // ideally we'd put this into the key instead to avoid needing to parse
        // TODO: handle seeking to first chunk offset
        // TODO: handle blocking on chunks still needing to be completed when
        // committing
        // TODO: handle concurrency properly, the access to eventsBySessionId
        // isn't threadsafe atm.
        // TODO: write data to file instead to reduce memory footprint
        messagesReceived.add(1)
        eventGroupsInFlight.addCallback((observableResult) =>
            observableResult.observe(Object.keys(eventsBySessionId).length)
        )

        const sessionId = message.headers.sessionId.toString()
        const windowId = message.headers.windowId.toString()
        const eventId = message.headers.eventId.toString()
        const distinctId = message.headers.distinctId.toString()
        const eventSource = Number.parseInt(message.headers.eventSource.toString())
        const eventType = Number.parseInt(message.headers.eventType.toString())
        const teamId = Number.parseInt(message.headers.teamId.toString())
        const unixTimestamp = Number.parseInt(message.headers.unixTimestamp.toString())
        const chunkCount = Number.parseInt(message.headers.chunkCount.toString())
        const chunkIndex = Number.parseInt(message.headers.chunkIndex.toString())

        let eventGroup = eventsBySessionId[sessionId]

        console.debug({
            action: 'start',
            uuid: eventId,
            sessionId: sessionId,
        })

        const commitEventGroupToS3 = async () => {
            const baseKey = `session_recordings/team_id/${eventGroup.teamId}/session_id/${eventGroup.sessionId}`
            const dataKey = `${baseKey}/data/${eventGroup.oldestEventTimestamp}-${eventGroup.oldestOffset}`
            const metaDataEventSummaryKey = `${baseKey}/metadata/event_summaries/${eventGroup.oldestEventTimestamp}-${eventGroup.oldestOffset}`
            const metaDataKey = `${baseKey}/metadata/metadata.json`

            console.debug({ action: 'committing_event_group', sessionId: eventGroup.sessionId, key: dataKey })

            const sendStartTime = performance.now()
            await s3Client.send(
                new PutObjectCommand({
                    Bucket: 'posthog',
                    Key: metaDataEventSummaryKey,
                    Body: getEventSummaryMetadata(eventGroup),
                })
            )
            await s3Client.send(
                new PutObjectCommand({
                    Bucket: 'posthog',
                    Key: metaDataKey,
                    Body: JSON.stringify({ distinctId: eventGroup.distinctId }),
                })
            )
            await s3Client.send(
                new PutObjectCommand({
                    Bucket: 'posthog',
                    Key: dataKey,
                    Body: getEventGroupDataString(eventGroup),
                })
            )
            const sendEndTime = performance.now()
            s3PutObjectTime.record(sendEndTime - sendStartTime)

            const otherSessions = Object.values(eventsBySessionId).filter(
                (otherEventGroup) => eventGroup.sessionId === otherEventGroup.sessionId
            )

            if (otherSessions.length) {
                // If there are other event groups still in flight, then update the
                // offset to the oldest message referenced by them.
                const offset = otherSessions.map((eventGroup) => eventGroup.oldestOffset).sort()[0]

                console.debug({ action: 'committing_offset', offset: offset, partition })

                consumer.commitOffsets([
                    {
                        topic,
                        partition,
                        offset: offset,
                    },
                ])

                eventGroupsInFlight.addCallback((observableResult) =>
                    observableResult.observe(Object.keys(eventsBySessionId).length)
                )
            } else {
                // If we are the only event group in flight then update to the newest
                // message in the event group.
                consumer.commitOffsets([
                    {
                        topic,
                        partition,
                        offset: (Number.parseInt(eventGroup.newestOffset) + 1).toString(),
                    },
                ])
            }

            delete eventsBySessionId[eventGroup.sessionId]
            eventGroupsCommittedCounter.add(1)
        }

        const createNewEventGroup = () => {
            const eventGroup: RecordingEventGroup = {
                events: {} as Record<string, RecordingEvent>,
                size: 0,
                teamId: teamId,
                sessionId: sessionId,
                oldestEventTimestamp: unixTimestamp,
                distinctId: distinctId,
                oldestOffset: message.offset,
                newestOffset: message.offset,
            }
            eventGroup.timer = setTimeout(() => commitEventGroupToS3(), maxEventGroupAge)
            console.debug({ action: 'create_event_group', sessionId: eventGroup.sessionId })
            return eventGroup
        }

        if (!eventGroup) {
            eventGroup = eventsBySessionId[sessionId] = createNewEventGroup()
            eventGroupsStarted.add(1, { reason: 'no-existing-event-group' })
        }

        // TODO: Handle incomplete recording events
        if (eventGroup.size + message.value.length > maxEventGroupSize) {
            clearTimeout(eventGroup.timer)
            commitEventGroupToS3()
            eventGroup = eventsBySessionId[eventGroup.sessionId] = createNewEventGroup()
            eventGroupsStarted.add(1, { reason: 'max-size-reached' })
        }

        const event: RecordingEvent = eventGroup.events[eventId] ?? {
            eventId: eventId,
            value: '',
            complete: false,
            timestamp: unixTimestamp,
            eventType: eventType,
            eventSource: eventSource,
            windowId: windowId,
        }

        event.value += message.value.toString()
        event.complete = chunkIndex + 1 === chunkCount
        eventGroup.events[event.eventId] = event
        eventGroup.size += message.value.length
        eventGroup.newestOffset = message.offset

        snapshotMessagesProcessed.add(1)
    },
})

// Make sure we log any errors we haven't handled
const errorTypes = ['unhandledRejection', 'uncaughtException']

errorTypes.map((type) => {
    process.on(type, async (e) => {
        try {
            console.debug(`process.on ${type}`)
            console.error(e)
            await consumer.disconnect()
            process.exit(0)
        } catch (_) {
            process.exit(1)
        }
    })
})

// Make sure we disconnect the consumer before shutdown, especially important
// for the test use case as we'll end up having to wait for and old registered
// consumers to timeout.
const signalTraps = ['SIGTERM', 'SIGINT', 'SIGUSR2']

signalTraps.map((type) => {
    process.once(type, async () => {
        try {
            await consumer.disconnect()
        } finally {
            process.kill(process.pid, type)
        }
    })
})
