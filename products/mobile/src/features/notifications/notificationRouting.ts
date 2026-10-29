import { asRecord } from '@/lib/records'

// Inbox pushes (`products/signals/backend/inbox_push_notifications.py`) and snooze reminders carry `{ type: 'report',
// report_id, project_id, notificationKind }`. Task pushes (`products/tasks/backend/push_dispatcher.py`) carry
// `{ taskId, taskRunId?, messageId?, projectId, notificationKind }`. Pushes sent before the server added `projectId`
// have no project, so routing searches the user's projects for the task.

/** Task lookups stop after this many projects, so a stale push cannot fan out over a large account. */
export const MAX_TASK_LOOKUPS = 8

export type TaskLookup = { found: true; reportId: string | null } | { found: false }

export interface NotificationRouteContext {
    currentProjectId: number | null
    projectIds: readonly number[]
    findTask: (projectId: number, taskId: string) => Promise<TaskLookup>
}

export interface NotificationRoute {
    pathname: string
    switchToProjectId: number | null
}

type NotificationData = Record<string, unknown>

export interface NotificationTarget {
    type: 'report' | 'task'
    id: string
    projectId: number | null
}

function asNonEmptyString(value: unknown): string | null {
    if (typeof value === 'string' && value.trim()) {
        return value.trim()
    }
    if (typeof value === 'number' && Number.isFinite(value)) {
        return String(value)
    }
    return null
}

function asProjectId(value: unknown): number | null {
    const number = typeof value === 'string' ? Number(value) : value
    return typeof number === 'number' && Number.isInteger(number) && number > 0 ? number : null
}

const INBOX: NotificationRoute = { pathname: '/inbox', switchToProjectId: null }

export function notificationTarget(data: unknown): NotificationTarget | null {
    const record = asRecord(data)
    if (!record) {
        return null
    }
    if (record.type === 'report') {
        const id = asNonEmptyString(record.report_id)
        return id ? { type: 'report', id, projectId: asProjectId(record.project_id) } : null
    }
    const id = asNonEmptyString(record.taskId)
    return id ? { type: 'task', id, projectId: asProjectId(record.projectId) } : null
}

export function notificationKind(data: unknown): string {
    const record = asRecord(data)
    if (!record) {
        return 'unknown'
    }
    const kind = asNonEmptyString(record.notificationKind)
    if (record.type === 'report') {
        return kind ?? 'report'
    }
    if (asNonEmptyString(record.taskId)) {
        return kind ?? 'task'
    }
    return 'unknown'
}

function reportRoute(record: NotificationData, context: NotificationRouteContext): NotificationRoute | null {
    const reportId = asNonEmptyString(record.report_id)
    if (!reportId) {
        return null
    }
    const pathname = `/report/${encodeURIComponent(reportId)}`
    const projectId = asProjectId(record.project_id)
    if (projectId === null || projectId === context.currentProjectId) {
        return { pathname, switchToProjectId: null }
    }
    if (context.projectIds.includes(projectId)) {
        return { pathname, switchToProjectId: projectId }
    }
    // The report lives in a project this user cannot open from the app.
    return INBOX
}

/** Only the push's own project when it names one, so a task in a project the user cannot open goes to the inbox. */
function taskLookupOrder(pushProjectId: number | null, context: NotificationRouteContext): number[] {
    const current = context.currentProjectId
    if (pushProjectId !== null) {
        return pushProjectId === current || context.projectIds.includes(pushProjectId) ? [pushProjectId] : []
    }
    return [
        ...(current !== null ? [current] : []),
        ...context.projectIds.filter((candidate) => candidate !== current),
    ].slice(0, MAX_TASK_LOOKUPS)
}

async function taskRoute(
    taskId: string,
    pushProjectId: number | null,
    context: NotificationRouteContext,
    openChat: boolean
): Promise<NotificationRoute> {
    const current = context.currentProjectId
    for (const projectId of taskLookupOrder(pushProjectId, context)) {
        let lookup: TaskLookup
        try {
            lookup = await context.findTask(projectId, taskId)
        } catch {
            return INBOX
        }
        if (!lookup.found) {
            continue
        }
        return {
            pathname:
                lookup.reportId && !openChat
                    ? `/report/${encodeURIComponent(lookup.reportId)}`
                    : `/chat?taskId=${encodeURIComponent(taskId)}`,
            switchToProjectId: projectId === current ? null : projectId,
        }
    }
    return INBOX
}

export async function resolveNotificationRoute(
    data: unknown,
    context: NotificationRouteContext
): Promise<NotificationRoute | null> {
    const record = asRecord(data)
    if (!record) {
        return null
    }
    if (record.type === 'report') {
        return reportRoute(record, context)
    }
    const taskId = asNonEmptyString(record.taskId)
    if (taskId) {
        return taskRoute(taskId, asProjectId(record.projectId), context, record.type === 'task')
    }
    return null
}
