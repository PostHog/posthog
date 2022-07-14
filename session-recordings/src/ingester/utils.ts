import { RecordingEvent, RecordingEventGroup } from '../types'

export const getEventGroupDataString = (recordingEventGroup: RecordingEventGroup) => {
    const events = Object.values(recordingEventGroup.events)
    const eventDataStrings = events.sort((a, b) => a.timestamp - b.timestamp).map((event) => event.value)
    return eventDataStrings.join('\n')
}

export const getEventGroupMetadata = (recordingEventGroup: RecordingEventGroup) => {
    const eventSummaries = Object.values(recordingEventGroup.events)
        .filter((event) => event.complete)
        .sort((a, b) => a.timestamp - b.timestamp)
        .map((event) =>
            JSON.stringify({
                eventSource: event.eventSource,
                eventType: event.eventType,
                windowId: event.windowId,
                timestamp: event.timestamp,
            })
        )
    return eventSummaries.join('\n')
}
