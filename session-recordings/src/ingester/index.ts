import { Kafka } from 'kafkajs'
import { PutObjectCommand } from '@aws-sdk/client-s3'
import { RecordingEvent, RecordingEventChunkMessage, RecordingEventGroup } from '../types'
import { s3Client } from '../s3'
import { meterProvider } from './metrics'
import { performance } from 'perf_hooks'
import { getEventGroupDataString } from './utils'

const maxEventGroupAge = Number.parseInt(
    process.env.MAX_EVENT_GROUP_AGE || process.env.NODE_ENV === 'dev' ? '1000' : '300000'
)
const maxEventGroupSize = Number.parseInt(
    process.env.MAX_EVENT_GROUP_SIZE || process.env.NODE_ENV === 'dev' ? '1000' : '1000000'
)

const kafka = new Kafka({
    clientId: 'ingester',
    brokers: ['localhost:9092'],
})

const consumer = kafka.consumer({
    groupId: `session-recordings-ingestion`,
})

consumer.connect()
consumer.subscribe({ topic: 'recording_events_to_object_storage' })

const eventsBySessionId: { [key: string]: RecordingEventGroup } = {}

// Define the metrics we'll be exposing at /metrics
const meter = meterProvider.getMeter('ingester')
const messagesReceived = meter.createCounter('messages_received')
const nonSnapshotsDiscarded = meter.createCounter('non_snapshots_discarded')
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
        // TODO: use the key to provide routing information
        // TODO: handle concurrency properly, the access to eventsBySessionId
        // isn't threadsafe atm.
        // OPTIONAL: stream data to S3
        // OPTIONAL: use parquet to reduce reads for e.g. timerange querying
        messagesReceived.add(1)
        eventGroupsInFlight.addCallback((observableResult) =>
            observableResult.observe(Object.keys(eventsBySessionId).length)
        )
        const recordingEventChunkString = message.value.toString('utf-8')
        const recordingEventChunk: RecordingEventChunkMessage = JSON.parse(recordingEventChunkString)

        let eventGroup = eventsBySessionId[recordingEventChunk.session_id]

        console.debug({
            action: 'start',
            uuid: recordingEventChunk.recording_event_id,
            session_id: recordingEventChunk.session_id,
        })

        const commitEventGroupToS3 = async () => {
            const dataKey = `team_id/${eventGroup.teamId}/session_id/${eventGroup.sessionId}/data/${eventGroup.oldestEventTimestamp}-${eventGroup.oldestOffset}`

            // TODO: calculate metadata and write it to this key
            const metaDataKey = `team_id/${eventGroup.teamId}/session_id/${eventGroup.sessionId}/metadata/${eventGroup.oldestEventTimestamp}-${eventGroup.oldestOffset}`

            console.debug({ action: 'committing_event_group', session_id: eventGroup.sessionId, key: dataKey })

            const sendStartTime = performance.now()
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
                        offset: eventGroup.newestOffset,
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
                teamId: recordingEventChunk.team_id,
                sessionId: recordingEventChunk.session_id,
                oldestEventTimestamp: recordingEventChunk.unix_timestamp,
                oldestOffset: message.offset,
                newestOffset: message.offset,
            }
            eventGroup.timer = setTimeout(() => commitEventGroupToS3(), maxEventGroupAge)
            console.debug({ action: 'create_event_group', session_id: eventGroup.sessionId })
            return eventGroup
        }

        if (!eventGroup) {
            eventGroup = eventsBySessionId[recordingEventChunk.session_id] = createNewEventGroup()
            eventGroupsStarted.add(1, { reason: 'no-existing-event-group' })
        }

        // TODO: Handle incomplete recording events
        if (eventGroup.size + recordingEventChunk.recording_event_data_chunk.length > maxEventGroupSize) {
            clearTimeout(eventGroup.timer)
            commitEventGroupToS3()
            eventGroup = eventsBySessionId[eventGroup.sessionId] = createNewEventGroup()
            eventGroupsStarted.add(1, { reason: 'max-size-reached' })
        }

        const event =
            eventGroup.events[recordingEventChunk.recording_event_id] ??
            ({
                eventId: recordingEventChunk.recording_event_id,
                chunkCount: recordingEventChunk.chunk_count,
                chunks: {} as Record<number, string>,
                timestamp: recordingEventChunk.unix_timestamp,
                eventType: recordingEventChunk.recording_event_type,
                eventSource: recordingEventChunk.recording_event_source,
                windowId: recordingEventChunk.window_id,
            } as RecordingEvent)
        event.chunks[recordingEventChunk.chunk_index] = recordingEventChunk.recording_event_data_chunk
        eventGroup.events[event.eventId] = event
        eventGroup.size += recordingEventChunk.recording_event_data_chunk.length
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
