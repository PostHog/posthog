import { KafkaTopic } from '../types'
import { consumer, producer } from '../utils/kafka'
import { config } from '../config'
import { Orchestrator } from './orchestrator'

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

const orchestrator = new Orchestrator()

export const startConsumer = (): void => {
    consumer.connect()
    consumer.subscribe({ topics: RECORDING_EVENTS_TOPICS })
    producer.connect()

    consumer.run({
        autoCommit: false,
        eachMessage: async (message) => {
            // TODO: handle seeking to first chunk offset
            // TODO: Handle duplicated data being stored in the case of a consumer restart
            orchestrator.handleKafkaMessage(message)

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
