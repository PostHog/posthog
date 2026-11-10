import type { RunAlertKind } from '../types/streamTypes'

export const RUN_ALERT_TITLES: Record<RunAlertKind, string> = {
    reconnecting: 'Restoring conversation',
    connection_failed: 'Connection lost',
    agent_error: 'Run stopped',
    agent_error_continued: 'Agent error',
    agent_crash: 'Agent stopped unexpectedly',
    message_undelivered: 'Message not delivered',
}
