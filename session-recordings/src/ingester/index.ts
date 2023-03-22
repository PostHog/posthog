import { IncomingRecordingMessage, KafkaTopic } from '../types'
import { meterProvider } from '../utils/metrics'
import pino from 'pino'
import { consumer, producer } from '../utils/kafka'
import { config } from '../config'
import { Orchestrator } from './orchestrator'

const logger = pino({ name: 'ingester', level: process.env.LOG_LEVEL || 'info' })

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

// Define the metrics we'll be exposing at /metrics
const meter = meterProvider.getMeter('ingester')
const messagesReceived = meter.createCounter('messages_received')
const snapshotMessagesProcessed = meter.createCounter('snapshot_messages_processed')

// TODO: Add timeout for buffers to be flushed
// TODO: Decompress buffered data
// TODO: Compress file before uploading to S3
// TODO: Configure TTL for S3 items

// TODO: Forward minimal event info to Kafka topic to Clickhouse

const orchestrator = new Orchestrator()

export const startConsumer = (): void => {
    consumer.connect()
    consumer.subscribe({ topics: RECORDING_EVENTS_TOPICS })
    producer.connect()

    consumer.run({
        autoCommit: false,
        eachMessage: async ({ topic, partition, message }) => {
            // TODO: handle seeking to first chunk offset
            // TODO: Handle duplicated data being stored in the case of a consumer restart
            messagesReceived.add(1)

            const parsedMessage = JSON.parse(message.value.toString())
            const parsedData = JSON.parse(parsedMessage.data)

            if (parsedData.event !== '$snapshot') {
                logger.debug('Received non-snapshot message, ignoring')
                return
            }

            const $snapshot_data = parsedData.properties.$snapshot_data

            const recordingMessage: IncomingRecordingMessage = {
                kafkaOffset: message.offset,
                kafkaPartition: partition,
                kafkaTopic: topic,

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

            orchestrator.consume(recordingMessage)

            // 1. Parse the message
            // 2. Get or create the SessionManager by sessionId
            // 3. Add the message to the SessionManager (which writes the data to file and keeps track of the offsets)
            // 3a. Chunked messages are handled in memory separately until the last chunk is received and then added to the "handled" messages
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
