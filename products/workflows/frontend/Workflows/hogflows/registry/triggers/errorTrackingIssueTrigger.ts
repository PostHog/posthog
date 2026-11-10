import { HogFlowAction } from '../../types'

export const ERROR_TRACKING_ISSUE_CREATED_EVENT = '$error_tracking_issue_created'

type InternalEventTriggerConfig = Extract<
    Extract<HogFlowAction, { type: 'trigger' }>['config'],
    { type: 'internal-event' }
>

export function isErrorTrackingIssueCreatedTriggerConfig(config: unknown): config is InternalEventTriggerConfig {
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
        events.length === 1 &&
        events[0]?.id === ERROR_TRACKING_ISSUE_CREATED_EVENT
    )
}
