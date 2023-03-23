import { EachMessagePayload } from 'kafkajs'
import { counterMessagesReceived } from '../utils/metrics'
import { IncomingRecordingMessage } from '../types'
import { SessionManager } from './session-manager'
import { createLogger } from '../utils/logger'

const logger = createLogger('orchestrator')

// TODO: Add timeout for buffers to be flushed
// TODO: Decompress buffered data
// TODO: Compress file before uploading to S3
// TODO: Configure TTL for S3 items
// TODO: Forward minimal event info to Kafka topic to Clickhouse

// TODO: This should manage state of sessions, dropping them if flushes are finished
export class Orchestrator {
    sessions: Map<string, SessionManager> = new Map()

    public async consume(event: IncomingRecordingMessage): Promise<void> {
        const key = `${event.team_id}-${event.session_id}`

        if (!this.sessions.has(key)) {
            this.sessions.set(
                key,
                new SessionManager(event.team_id, event.session_id, () => {
                    // If the SessionManager is done (flushed and with no more queued events) then we remove it to free up memory
                    this.sessions.delete(key)
                })
            )
        }

        await this.sessions.get(key).add(event)
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

        this.consume(recordingMessage)
    }
}
