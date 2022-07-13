export type RecordingEventGroup = {
    teamId: number
    sessionId: string
    // TODO: replace string[] with a file handle that we can append to
    events: Record<string, RecordingEvent>
    size: number
    oldestEventTimestamp: number
    oldestOffset: string
    newestOffset: string
    timer?: NodeJS.Timeout
}

export type RecordingEvent = {
    eventId: string
    value: string
    complete: boolean
    timestamp: number
    eventType: number
    eventSource: number
    windowId: string
}
