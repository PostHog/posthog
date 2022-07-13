import { RecordingEvent, RecordingEventGroup } from '../types'

export const getEventGroupDataString = (recordingEventGroup: RecordingEventGroup) => {
    const events = Object.values(recordingEventGroup.events)
    const eventDataStrings = events.sort((a, b) => a.timestamp - b.timestamp).map((event) => event.value)
    return eventDataStrings.join('\n')
}
