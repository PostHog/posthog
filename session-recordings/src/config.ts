export const config = {
    topics: {
        sessionRecordingEvents: process.env.SESSION_RECORDING_EVENTS || 'session_recording_events',
        sessionRecordingEventsDeadLetter:
            process.env.SESSION_RECORDING_EVENTS_DEAD_LETTER || 'session_recording_events_dead_letter',
    },

    consumerConfig: {
        groupId: `object-storage-ingester`,
        sessionTimeout: 30000,
        heartbeatInterval: 6000,
    },
}
