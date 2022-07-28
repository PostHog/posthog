import { KafkaMessage, Message } from 'kafkajs'
import { KafkaTopic, RecordingEvent, RecordingEventGroup, RecordingMessage } from '../types'

export const getEventGroupDataString = (recordingEventGroup: RecordingEventGroup) => {
    const eventDataStrings = recordingEventGroup.events
        .sort((a, b) => a.timestamp - b.timestamp)
        .map((event) => event.messages.map((message) => message.value).join(''))
    return eventDataStrings.join('\n')
}

export const getEventSummaryMetadata = (recordingEventGroup: RecordingEventGroup) => {
    const eventSummaries = Object.values(recordingEventGroup.events)
        .filter((event) => event.complete)
        .sort((a, b) => a.timestamp - b.timestamp)
        .map((event) =>
            JSON.stringify({
                source: event.eventSource,
                type: event.eventType,
                windowId: event.windowId,
                timestamp: event.timestamp,
            })
        )
    return eventSummaries.join('\n')
}

export const getEventSize = (recordingEvent: RecordingEvent) => {
    return recordingEvent.messages.reduce((acc, message) => acc + message.value.length, 0)
}

export const convertRecordingMessageToKafkaMessage = (recordingMessage: RecordingMessage): Message => {
    return {
        key: recordingMessage.kafkaKey,
        value: recordingMessage.value,
        headers: {
            sessionId: recordingMessage.sessionId,
            windowId: recordingMessage.windowId,
            eventId: recordingMessage.eventId,
            distinctId: recordingMessage.distinctId,
            eventSource: recordingMessage.eventSource.toString(),
            eventType: recordingMessage.eventType.toString(),
            teamId: recordingMessage.teamId.toString(),
            unixTimestamp: recordingMessage.timestamp.toString(),
            chunkCount: recordingMessage.chunkCount.toString(),
            chunkIndex: recordingMessage.chunkIndex.toString(),
            originalKafkaOffset: recordingMessage.originalKafkaOffset.toString(),
        },
    }
}

export const convertKafkaMessageToRecordingMessage = (
    kafkaMessage: KafkaMessage,
    topic: KafkaTopic,
    partition: number
): RecordingMessage => {
    return {
        sessionId: kafkaMessage.headers.sessionId.toString(),
        windowId: kafkaMessage.headers.windowId.toString(),
        eventId: kafkaMessage.headers.eventId.toString(),
        distinctId: kafkaMessage.headers.distinctId.toString(),
        eventSource: Number.parseInt(kafkaMessage.headers.eventSource.toString()),
        eventType: Number.parseInt(kafkaMessage.headers.eventType.toString()),
        teamId: Number.parseInt(kafkaMessage.headers.teamId.toString()),
        timestamp: Number.parseInt(kafkaMessage.headers.unixTimestamp.toString()),
        chunkCount: Number.parseInt(kafkaMessage.headers.chunkCount.toString()),
        chunkIndex: Number.parseInt(kafkaMessage.headers.chunkIndex.toString()),
        value: kafkaMessage.value.toString(),
        kafkaOffset: Number.parseInt(kafkaMessage.offset),
        originalKafkaOffset:
            topic === 'recording_events'
                ? Number.parseInt(kafkaMessage.offset)
                : Number.parseInt(kafkaMessage.headers.originalKafkaOffset.toString()),
        kafkaTopic: topic,
        kafkaPartition: partition,
        kafkaKey: kafkaMessage.key?.toString(),
    }
}

export const getTopicPartitionKey = (topic: string, partition: number) => `${topic}-${partition}`
export const getTopicAndPartitionFromKey = (topicPartitionKey: string) => {
    const [topic, partition] = topicPartitionKey.split('-')
    return { topic, partition: Number.parseInt(partition) }
}
