import { KafkaMessage, Message } from 'kafkajs'
import { RecordingEvent, RecordingEventGroup, RecordingMessage } from '../types'

export const getEventGroupDataString = (recordingEventGroup: RecordingEventGroup) => {
    const events = Object.values(recordingEventGroup.events)
    const eventDataStrings = events
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
        },
    }
}

export const convertKafkaMessageToRecordingMessage = (
    kafkaMessage: KafkaMessage,
    topic: string,
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
        kafkaTopic: topic,
        kafkaPartition: partition,
        kafkaKey: kafkaMessage.key?.toString(),
    }
}
