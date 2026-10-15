/** pinned: internal event name emitted by Signals (products/signals/backend/workflow_events.py) */
export const INBOX_REPORT_READY_EVENT = '$inbox_report_ready'

/** The properties a run's event carries, mirroring InboxReportReadyProperties in workflow_events.py. */
export const INBOX_REPORT_PROPERTIES = [
    { key: 'report_id', description: 'The report ID', example: 'report123' },
    { key: 'title', description: 'The report title', example: 'Example report title' },
    { key: 'summary', description: 'The researched summary', example: 'Example report summary' },
    { key: 'priority', description: 'P0 to P4, or empty when the report has no priority', example: 'P2' },
    {
        key: 'source_products',
        description: 'The products whose signals the report groups',
        example: ['error_tracking'],
    },
    {
        key: 'report_url',
        description: 'A link to the report in Inbox',
        example: 'https://us.posthog.com/project/1/inbox/reports/report123',
    },
] as const

export function exampleInboxReportProperties(): Record<string, unknown> {
    return Object.fromEntries(INBOX_REPORT_PROPERTIES.map(({ key, example }) => [key, example]))
}

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
