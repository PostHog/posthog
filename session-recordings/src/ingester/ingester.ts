import { EachMessagePayload } from 'kafkajs'
import { counterMessagesReceived } from '../utils/metrics'
import { IncomingRecordingMessage, KafkaTopic } from '../types'
import { SessionManager } from './session-manager'
import { createLogger } from '../utils/logger'
import { config } from '../config'
import { consumer, producer } from '../utils/kafka'
import { OffsetManager } from './offset-manager'

const logger = createLogger('ingester')

const RECORDING_EVENTS_DEAD_LETTER_TOPIC = config.topics.sessionRecordingEventsDeadLetter

type TopicConfig = {
    retryTopic: string
    timeout: number
}

const baseTopic = config.topics.sessionRecordingEvents

const RECORDING_EVENTS_TOPICS_CONFIGS: Record<KafkaTopic, TopicConfig> = {
    [`${baseTopic}`]: { timeout: 0, retryTopic: `${baseTopic}_retry_1` },
    [`${baseTopic}_retry_1`]: { timeout: 2 * 1000, retryTopic: `${baseTopic}_retry_2` },
    [`${baseTopic}_retry_2`]: { timeout: 30 * 1000, retryTopic: `${baseTopic}_retry_3` },
    [`${baseTopic}_retry_3`]: { timeout: 5 * 60 * 1000, retryTopic: RECORDING_EVENTS_DEAD_LETTER_TOPIC },
}
const RECORDING_EVENTS_TOPICS = Object.keys(RECORDING_EVENTS_TOPICS_CONFIGS) as KafkaTopic[]

// TODO: Add timeout for buffers to be flushed
// TODO: Compress file before uploading to S3
// TODO: Configure TTL for S3 items (this can only be done as lifecycle policy)
// TODO: Forward minimal event info to Kafka topic to Clickhouse

export class Ingester {
    sessions: Map<string, SessionManager> = new Map()
    offsetManager = new OffsetManager()

    // TODO: Have a timer here that runs every N seconds and calls `flushIfNecessary` on all sessions

    public async consume(event: IncomingRecordingMessage): Promise<void> {
        const { team_id, session_id } = event
        const key = `${team_id}-${session_id}`

        const { partition, topic, offset } = event.metadata
        this.offsetManager.addOffset(topic, partition, offset)

        if (!this.sessions.has(key)) {
            const { partition, topic } = event.metadata

            const sessionManager = new SessionManager(team_id, session_id, partition, topic, (offsets) => {
                this.offsetManager.removeOffsets(topic, partition, offsets)

                // If the SessionManager is done (flushed and with no more queued events) then we remove it to free up memory
                if (sessionManager.isEmpty) {
                    this.sessions.delete(key)
                }
            })

            this.sessions.set(key, sessionManager)
        }

        await this.sessions.get(key).add(event)
        // TODO: If we error here, what should we do...?
        // If it is unrecoverable we probably want to remove the offset
        // If it is recoverable, we probably want to retry?
    }

    public async handleKafkaMessage({ topic, partition, message }: EachMessagePayload): Promise<void> {
        // TODO: handle seeking to first chunk offset
        // TODO: Handle duplicated data being stored in the case of a consumer restart

        counterMessagesReceived.add(1)

        const parsedMessage = JSON.parse(message.value.toString())
        const parsedData = JSON.parse(parsedMessage.data)

        if (parsedData.event !== '$snapshot') {
            logger.debug('Received non-snapshot message, ignoring')
            return
        }

        const $snapshot_data = parsedData.properties.$snapshot_data

        const recordingMessage: IncomingRecordingMessage = {
            metadata: {
                partition,
                topic,
                offset: parseInt(message.offset),
            },

            team_id: parsedMessage.team_id,
            distinct_id: parsedMessage.distinct_id,
            session_id: parsedData.properties.$session_id,
            window_id: parsedData.properties.$window_id,

            // Properties data
            chunk_id: $snapshot_data.chunk_id,
            chunk_index: $snapshot_data.chunk_index,
            chunk_count: $snapshot_data.chunk_count,
            data: $snapshot_data.data,
            compresssion: $snapshot_data.compression,
            has_full_snapshot: $snapshot_data.has_full_snapshot,
            events_summary: $snapshot_data.events_summary,
        }

        this.consume(recordingMessage)
    }

    public start(): void {
        consumer.connect()
        consumer.subscribe({ topics: RECORDING_EVENTS_TOPICS })
        producer.connect()

        // TODO: Handle rebalancing event / consumer restart to ensure we don't double consume
        consumer.run({
            autoCommit: false,
            eachMessage: async (message) => {
                // TODO: handle seeking to first chunk offset
                // TODO: Handle duplicated data being stored in the case of a consumer restart
                await this.handleKafkaMessage(message)

                // 1. Parse the message
                // 2. Get or create the SessionManager by sessionId
                // 3. Add the message to the SessionManager (which writes the data to file and keeps track of the offsets)
                // 3b. All message offsets are saved (somehow) so that we know where to start reading from if the consumer restarts
                // 4. When the time or size threshold is reached, the SessionManager is flushed and the data is uploaded to S3
                // 5. We remove all the flushed event offsets from the SessionManager offset tracker and then commit the oldest offset found

                // const recordingMessage = convertKafkaMessageToRecordingMessage(message, topic as KafkaTopic, partition)

                // // TODO Do this without timeouts so order is maintained
                // const timeout_ms = RECORDING_EVENTS_TOPICS_CONFIGS[topic as KafkaTopic].timeout
                // if (timeout_ms !== 0) {
                //     setTimeout(() => {
                //         handleMessage(recordingMessage)
                //     }, timeout_ms)
                // } else {
                //     handleMessage(recordingMessage)
                // }
            },
        })
    }

    public async stop(): Promise<void> {
        await consumer.disconnect()
        await producer.disconnect()

        // TODO: Ditch all in progress sessions
        // This is inefficient but currently necessary due to new instances restarting from the commited offset point

        const destroyPromises: Promise<void>[] = []
        this.sessions.forEach((sessionManager) => {
            destroyPromises.push(sessionManager.destroy())
        })

        await Promise.all(destroyPromises)
    }
}
