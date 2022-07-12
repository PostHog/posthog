import { Kafka } from 'kafkajs'
import { PutObjectCommand } from '@aws-sdk/client-s3'
import { gunzipSync } from 'zlib'
import { EventData, Event } from './types'
import { s3Client } from './s3'

const maxChunkAge = Number.parseInt(process.env.MAX_CHUNK_AGE || '1000')
const maxChunkSize = Number.parseInt(process.env.MAX_CHUNK_SIZE || '1000')

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
    team_id: string
    session_id: string
    // TODO: replace string[] with a file handle that we can append to
    events: string[]
    size: number
    oldestEventTimestamp: number
    oldestOffset: string
    timer?: NodeJS.Timeout
}
const eventsBySessionId: { [key: string]: Chunk } = {}

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
        const eventString = message.value.toString('utf-8')
        const event: Event = JSON.parse(eventString)

        if (event.event !== '$snapshot') {
            console.debug({ action: 'skipping', event: event.event, uuid: event.uuid })
            return
        }

        const eventData: EventData = JSON.parse(event.data)
        const snapshotData = gunzipSync(Buffer.from(eventData.properties.$snapshot_data.data, 'base64')).toString(
            'utf-8'
        )
        const sessionId = eventData.properties.$session_id
        let chunk = eventsBySessionId[eventData.properties.$session_id]

        console.debug({ action: 'start', uuid: event.uuid, event: event.event, session_id: sessionId })

        const commitChunkToS3 = async () => {
            const key = `team_id/${chunk.team_id}/session_id/${chunk.session_id}/chunks/${chunk.oldestEventTimestamp}-${chunk.oldestOffset}`

            console.debug({ action: 'commiting_chunk', session_id: chunk.session_id, key: key })

            await s3Client.send(
                new PutObjectCommand({
                    Bucket: 'posthog',
                    Key: key,
                    Body: chunk.events.join('\n'),
                })
            )

            if (eventsBySessionId.length) {
                const offset = Object.values(eventsBySessionId)
                    .filter((chunk) => sessionId === chunk.session_id)
                    .map((chunk) => chunk.oldestOffset)
                    .sort()[0]

                consumer.commitOffsets([
                    {
                        topic,
                        partition,
                        offset: offset,
                    },
                ])
                console.debug({ action: 'committed_offset', offset: offset, partition })
            }

            delete eventsBySessionId[sessionId]
        }

        if (!chunk) {
            console.debug({ action: 'create_chunk', session_id: sessionId })

            chunk = eventsBySessionId[sessionId] = {
                events: [] as string[],
                size: 0,
                team_id: event.team_id,
                session_id: sessionId,
                oldestEventTimestamp: event.timestamp,
                oldestOffset: message.offset,
            }
            chunk.timer = setTimeout(() => commitChunkToS3(), maxChunkAge)
        }

        if (chunk.size + eventString.length > maxChunkSize) {
            clearTimeout(chunk.timer)
            commitChunkToS3()

            console.debug({ action: 'create_chunk', session_id: chunk.session_id })
            chunk = eventsBySessionId[sessionId] = {
                events: [] as string[],
                size: 0,
                team_id: event.team_id,
                session_id: sessionId,
                oldestEventTimestamp: event.timestamp,
                oldestOffset: message.offset,
            }
            chunk.timer = setTimeout(() => commitChunkToS3(), maxChunkAge)
        }

        chunk.events.push(snapshotData)
        chunk.size += eventString.length
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
