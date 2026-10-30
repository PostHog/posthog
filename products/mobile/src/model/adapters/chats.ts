import type { ProjectScope } from '@/api/reports'
import type { TaskRunStatusApi, TaskSummaryApi } from '@/api/tasks'

import type { ChatListItem, ChatOrigin, ChatSessionStatus } from '../types'

const SESSION_STATUS: Record<TaskRunStatusApi, ChatSessionStatus> = {
    failed: 'failed',
    in_progress: 'working',
    queued: 'queued',
    not_started: 'starting',
    cancelled: 'stopped',
    completed: 'completed',
}

const SESSION_ORIGIN: Partial<Record<string, ChatOrigin>> = {
    posthog_ai: 'chat',
    signal_report: 'report',
}

function titleOr(title: string | null | undefined, fallback: string): string {
    return title?.trim() || fallback
}

export function taskWebUrl(scope: ProjectScope | null, taskId: string | null): string | undefined {
    return scope && taskId
        ? `${scope.host.replace(/\/$/, '')}/project/${scope.projectId}/ai?task=${encodeURIComponent(taskId)}`
        : undefined
}

function sessionStatus(session: TaskSummaryApi): ChatSessionStatus {
    const status = session.latest_run?.status
    return status ? (SESSION_STATUS[status] ?? 'idle') : 'idle'
}

function sessionOrigin(session: TaskSummaryApi): ChatOrigin {
    return SESSION_ORIGIN[session.origin_product] ?? 'session'
}

function sessionItem(session: TaskSummaryApi, scope: ProjectScope | null): ChatListItem {
    const output = session.latest_run?.output
    return {
        id: `session:${session.id}`,
        kind: 'session',
        sourceId: session.id,
        origin: sessionOrigin(session),
        title: titleOr(session.title, 'Untitled session'),
        updatedAt: session.last_activity_at ?? session.updated_at ?? session.created_at ?? '',
        status: sessionStatus(session),
        pullRequestUrl: output?.pr_url ?? output?.pr_urls?.[0] ?? null,
        webUrl: taskWebUrl(scope, session.id),
    }
}

/** Rows without a readable time sort last. Zero instead of -Infinity keeps the comparator from returning NaN. */
function sortTime(item: ChatListItem): number {
    const time = Date.parse(item.updatedAt)
    return Number.isNaN(time) ? 0 : time
}

/**
 * The person's sandbox sessions as chat rows, newest activity first. The server already leaves out archived tasks and
 * caps the page at `SESSION_LIST_LIMIT`.
 */
export function chatListFromSessions(
    sessions: TaskSummaryApi[] | undefined,
    scope: ProjectScope | null
): ChatListItem[] {
    const items = (sessions ?? []).map((session) => sessionItem(session, scope))
    return items.sort((a, b) => sortTime(b) - sortTime(a))
}
