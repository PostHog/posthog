/** pinned: internal event name emitted by Signals (products/signals/backend/workflow_events.py) */
export const INBOX_REPORT_READY_EVENT = '$inbox_report_ready'

export type InboxReportReadyTriggerConfig = {
    type: 'internal-event'
    filters: {
        source: 'internal-events'
        events: { id: string; type: 'events' }[]
        properties?: any[]
    }
}

// Callers pass whatever trigger a workflow carries, including legacy and malformed shapes, so
// every level is checked before it is read.
export function isInboxReportReadyTriggerConfig(config: unknown): config is InboxReportReadyTriggerConfig {
    if (!config || typeof config !== 'object') {
        return false
    }
    const { type, filters } = config as { type?: unknown; filters?: unknown }
    if (type !== 'internal-event' || !filters || typeof filters !== 'object') {
        return false
    }
    const { source, events } = filters as { source?: unknown; events?: unknown }
    return (
        source === 'internal-events' &&
        Array.isArray(events) &&
        events.some(
            (event) => event && typeof event === 'object' && (event as { id?: unknown }).id === INBOX_REPORT_READY_EVENT
        )
    )
}
