import { Kafka } from 'kafkajs'
import { PutObjectCommand } from '@aws-sdk/client-s3'
import { gunzipSync } from 'zlib'
import { EventData, Event, SessionData } from '../types'
import { s3Client } from '../s3'
import { meterProvider } from './metrics'
import { performance } from 'perf_hooks'

const maxChunkAge = Number.parseInt(process.env.MAX_CHUNK_AGE || process.env.NODE_ENV === 'dev' ? '1000' : '300000')
const maxChunkSize = Number.parseInt(process.env.MAX_CHUNK_SIZE || process.env.NODE_ENV === 'dev' ? '1000' : '1000000')

const kafka = new Kafka({
    clientId: 'ingester',
    brokers: ['localhost:9092'],
})

const consumer = kafka.consumer({
    groupId: `session-recordings-ingestion`,
})

consumer.connect()
consumer.subscribe({ topic: 'events_plugin_ingestion' })

type Chunk = {
    teamId: string
    sessionId: string
    windowId: string
    // TODO: replace string[] with a file handle that we can append to
    events: string[]
    size: number
    oldestEventTimestamp: number
    oldestOffset: string
    newestOffset: string
    timer?: NodeJS.Timeout
}

const eventsBySessionId: { [key: string]: Chunk } = {}

// Define the metrics we'll be exposing at /metrics
const meter = meterProvider.getMeter('ingester')
const messagesReceived = meter.createCounter('messages_received')
const nonSnapshotsDiscarded = meter.createCounter('non_snapshots_discarded')
const snapshotMessagesProcessed = meter.createCounter('snapshot_messages_processed')
const chunksCommittedCounter = meter.createCounter('chunks_committed')
const chunksStarted = meter.createCounter('chunks_started')
const chunksInFlight = meter.createObservableGauge('chunks_in_flight', {
    description: "Number of chunks that haven't been committed to S3 yet.",
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
        chunksInFlight.addCallback((observableResult) =>
            observableResult.observe(Object.keys(eventsBySessionId).length)
        )
        const eventString = message.value.toString('utf-8')
        const event: Event = JSON.parse(eventString)

        if (event.event !== '$snapshot') {
            nonSnapshotsDiscarded.add(1)
            console.debug({ action: 'skipping', event: event.event, uuid: event.uuid })
            return
        }

        const eventData: EventData = JSON.parse(event.data)
        const snapshotData: SessionData = JSON.parse(
            gunzipSync(Buffer.from(eventData.properties.$snapshot_data.data, 'base64')).toString('utf-8')
        )
        const sessionId = eventData.properties.$session_id
        const windowId = eventData.properties.$window_id
        let chunk = eventsBySessionId[eventData.properties.$session_id]

        console.debug({ action: 'start', uuid: event.uuid, event: event.event, session_id: sessionId })

        const commitChunkToS3 = async () => {
            const key = `team_id/${chunk.teamId}/session_id/${chunk.sessionId}/window_id/${chunk.windowId}/chunks/${chunk.oldestEventTimestamp}-${chunk.oldestOffset}`

            console.debug({ action: 'committing_chunk', session_id: chunk.sessionId, key: key })

            const sendStartTime = performance.now()
            await s3Client.send(
                new PutObjectCommand({
                    Bucket: 'posthog',
                    Key: key,
                    Body: chunk.events.join('\n'),
                })
            )
            const sendEndTime = performance.now()
            s3PutObjectTime.record(sendEndTime - sendStartTime)

            const otherSessions = Object.values(eventsBySessionId).filter((chunk) => sessionId === chunk.sessionId)

            if (otherSessions.length) {
                // If there are other chunks still in flight, then update the
                // offset to the oldest message referenced by them.
                const offset = otherSessions.map((chunk) => chunk.oldestOffset).sort()[0]

                console.debug({ action: 'committing_offset', offset: offset, partition })

                consumer.commitOffsets([
                    {
                        topic,
                        partition,
                        offset: offset,
                    },
                ])

                chunksInFlight.addCallback((observableResult) =>
                    observableResult.observe(Object.keys(eventsBySessionId).length)
                )
            } else {
                // If we are the only chunk in flight then update to the newest
                // message in the chunk.
                consumer.commitOffsets([
                    {
                        topic,
                        partition,
                        offset: chunk.newestOffset,
                    },
                ])
            }

            delete eventsBySessionId[sessionId]
            chunksCommittedCounter.add(1)
        }

        const createNewChunk = () => {
            const chunk: Chunk = {
                events: [] as string[],
                size: 0,
                teamId: event.team_id,
                sessionId: sessionId,
                windowId: windowId,
                oldestEventTimestamp: event.timestamp,
                oldestOffset: message.offset,
                newestOffset: message.offset,
            }
            chunk.timer = setTimeout(() => commitChunkToS3(), maxChunkAge)
            console.debug({ action: 'create_chunk', session_id: chunk.sessionId })
            return chunk
        }

        if (!chunk) {
            chunk = eventsBySessionId[sessionId] = createNewChunk()
            chunksStarted.add(1, { reason: 'no-existing-chunk' })
        }

        if (chunk.size + eventString.length > maxChunkSize) {
            clearTimeout(chunk.timer)
            commitChunkToS3()
            chunk = eventsBySessionId[sessionId] = createNewChunk()
            chunksStarted.add(1, { reason: 'max-size-reached' })
        }

        chunk.events.push(...snapshotData.map((event) => JSON.stringify(event)))
        chunk.size += eventString.length
        chunk.newestOffset = message.offset

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
