import { Kafka } from 'kafkajs'
import { S3Client } from '@aws-sdk/client-s3'
import { PutObjectCommand } from '@aws-sdk/client-s3'

// Set the AWS Region.
const REGION = 'us-east-1' //e.g. "us-east-1"
// Create an Amazon S3 service client object.
const s3Client = new S3Client({
    region: REGION,
    endpoint: 'http://localhost:19000',
    credentials: {
        accessKeyId: 'object_storage_root_user',
        secretAccessKey: 'object_storage_root_password',
    },
    forcePathStyle: true, // Needed to work with MinIO
})

const maxChunkAge = 1000
const maxChunkSize = 1000

const kafka = new Kafka({
    clientId: 'ingester',
    brokers: ['localhost:9092'],
})

const consumer = kafka.consumer({
    groupId: 'session-recordings-ingestion',
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
        const eventString = message.value.toString()
        const event = JSON.parse(eventString)
        let chunk = eventsBySessionId[event.properties.$session_id]

        console.log(`Processing ${event.uuid}`)

        const commitChunkToS3 = async () => {
            delete eventsBySessionId[event.properties.$session_id]

            await s3Client.send(
                new PutObjectCommand({
                    Bucket: 'posthog',
                    Key: `team_id/${chunk.team_id}/session_id/${chunk.session_id}/chunks/${chunk.oldestEventTimestamp}-${chunk.oldestOffset}`,
                    Body: chunk.events.join('\n'),
                })
            )

            if (eventsBySessionId.length) {
                consumer.commitOffsets([
                    {
                        topic,
                        partition,
                        offset: Object.values(eventsBySessionId)
                            .map((chunk) => chunk.oldestOffset)
                            .sort()[0],
                    },
                ])
            }
        }

        if (!chunk) {
            console.log(`Creating new chunk for ${event.properties.$session_id}`)

            chunk = eventsBySessionId[event.properties.$session_id] = {
                events: [] as string[],
                size: 0,
                team_id: event.team_id,
                session_id: event.properties.$session_id,
                oldestEventTimestamp: event.timestamp,
                oldestOffset: message.offset,
            }
            chunk.timer = setTimeout(() => commitChunkToS3(), maxChunkAge)
        }

        if (chunk.size + eventString.length > maxChunkSize) {
            clearTimeout(chunk.timer)
            commitChunkToS3()

            console.log(`Creating new chunk for ${event.properties.$session_id}`)
            chunk = eventsBySessionId[event.properties.$session_id] = {
                events: [] as string[],
                size: 0,
                team_id: event.team_id,
                session_id: event.properties.$session_id,
                oldestEventTimestamp: event.timestamp,
                oldestOffset: message.offset,
            }
            chunk.timer = setTimeout(() => commitChunkToS3(), maxChunkAge)
        }

        chunk.events.push(eventString)
        chunk.size += eventString.length
    },
})

// Make sure we log any errors we haven't handled
const errorTypes = ['unhandledRejection', 'uncaughtException']

errorTypes.map((type) => {
    process.on(type, async (e) => {
        try {
            console.log(`process.on ${type}`)
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
