export type RecordingEventGroup = {
    id: string
    teamId: number
    sessionId: string
    distinctId: string // OK if this distinct ID changes through the recording, we just need to store a single distinct ID
    // TODO: replace string[] with a file handle that we can append to
    events: Record<string, RecordingEvent>
    size: number
    oldestEventTimestamp: number
    oldestOffset: number
    newestOffset: number
    timer?: NodeJS.Timeout
    status?: 'sending' | 'active'
}

export type RecordingEvent = {
    eventId: string
    messages: RecordingMessage[]
    complete: boolean
    timestamp: number
    eventType: number
    eventSource: number
    windowId: string
    sessionId: string
    distinctId: string
    teamId: number
    kafkaTopic: string
    kafkaPartition: number
    oldestOffset: number
    newestOffset: number
}

export type RecordingMessage = {
    eventId: string
    value: string
    timestamp: number
    eventType: number
    eventSource: number
    windowId: string
    sessionId: string
    distinctId: string
    chunkCount: number
    chunkIndex: number
    teamId: number
    kafkaTopic: string
    kafkaPartition: number
    kafkaOffset: number
    kafkaKey: string
}
