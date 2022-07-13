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
    chunkCount: number
    chunks: Record<number, string>
    timestamp: number
    eventType: number
    eventSource: number
    windowId: string
    distinctId: string
}

export type RecordingEventChunkMessage = {
    unix_timestamp: number
    recording_event_id: string
    session_id: string
    distinct_id: string
    chunk_count: number
    chunk_index: number
    recording_event_data_chunk: string
    recording_event_source?: number
    recording_event_type?: number
    window_id?: string
    team_id?: number
}
