import { RecordingEvent, RecordingEventGroup } from '../types'

export const isRecordingEventComplete = (recordingEvent: RecordingEvent) => {
    return Object.keys(recordingEvent.chunks).length === recordingEvent.chunkCount
}

export const isEntireEventGroupComplete = (recordingEventGroup: RecordingEventGroup) => {
    Object.values(recordingEventGroup.events).every(isRecordingEventComplete)
}

export const getEventGroupDataString = (recordingEventGroup: RecordingEventGroup) => {
    const events = Object.values(recordingEventGroup.events)
    const eventDataStrings = events
        .sort((a, b) => a.timestamp - b.timestamp)
        .map((event) => {
            const orderedChunksIndexes = Object.keys(event.chunks)
                .map(parseInt)
                .sort((a, b) => a - b)
            return orderedChunksIndexes.map((chunkIndex) => event.chunks[chunkIndex]).join('')
        })
    return '[' + eventDataStrings.join(',') + ']'
}
