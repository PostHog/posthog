export type RecordingEventGroup = {
    teamId: number
    sessionId: string
    distinctId: string // OK if this distinct ID changes through the recording, we just need to store a single distinct ID
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
