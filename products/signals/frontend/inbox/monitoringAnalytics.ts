// Only the Monitoring tab loads this, so its helpers stay out of the eagerly loaded inbox analytics.
import { INBOX_EVENTS, captureInboxEvent } from './inboxAnalytics'

/** A row on the Monitoring tab was opened to show its evidence. `finished` is true for a report that left Monitoring. */
export function captureMonitoringRowExpanded(params: { reportId: string; status: string; finished: boolean }): void {
    captureInboxEvent(INBOX_EVENTS.MONITORING_ROW_EXPANDED, {
        report_id: params.reportId,
        status: params.status,
        finished: params.finished,
    })
}

export function captureMonitoringScopeChanged(params: {
    everyone: boolean
    connections: string[]
    needsAttention?: boolean
}): void {
    captureInboxEvent(INBOX_EVENTS.MONITORING_SCOPE_CHANGED, {
        everyone: params.everyone,
        connections: params.connections,
        needs_attention: !!params.needsAttention,
    })
}

/** pinned: `action` values on `Inbox monitoring action`; dashboards break them down by name. */
export type MonitoringAction =
    | 'open_report'
    | 'open_pull_request'
    | 'open_follow_up'
    | 'load_more'
    | 'retry'
    | 'show_everyone'
    | 'show_all_statuses'

export function captureMonitoringAction(params: { action: MonitoringAction; reportId?: string }): void {
    captureInboxEvent(INBOX_EVENTS.MONITORING_ACTION, {
        action: params.action,
        report_id: params.reportId ?? null,
    })
}
