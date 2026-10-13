import type { ConversationSummaryApi } from '@/api/conversations'
import type { ProjectScope } from '@/api/reports'
import type { TaskRunStatusApi, TaskSummaryApi } from '@/api/tasks'

import type { ChatListItem, ChatSessionStatus } from '../types'

export const CHAT_LIST_LIMIT = 30

const SESSION_STATUS: Record<TaskRunStatusApi, ChatSessionStatus> = {
    failed: 'failed',
    in_progress: 'working',
    queued: 'queued',
    not_started: 'starting',
    cancelled: 'stopped',
    completed: 'completed',
}

function titleOr(title: string | null | undefined, fallback: string): string {
    return title?.trim() || fallback
}

function aiWebUrl(scope: ProjectScope | null, param: 'chat' | 'task', id: string): string | undefined {
    return scope ? `${scope.host}/project/${scope.projectId}/ai?${param}=${encodeURIComponent(id)}` : undefined
}

function sessionStatus(session: TaskSummaryApi): ChatSessionStatus {
    const status = session.latest_run?.status
    return status ? (SESSION_STATUS[status] ?? 'idle') : 'idle'
}

function sessionItem(session: TaskSummaryApi, scope: ProjectScope | null): ChatListItem {
    const output = session.latest_run?.output
    return {
        id: `session:${session.id}`,
        kind: 'session',
        sourceId: session.id,
        title: titleOr(session.title, 'Untitled session'),
        updatedAt: session.last_activity_at ?? session.updated_at ?? session.created_at ?? '',
        status: sessionStatus(session),
        pullRequestUrl: output?.pr_url ?? output?.pr_urls?.[0] ?? null,
        webUrl: aiWebUrl(scope, 'task', session.id),
    }
}

function conversationItem(conversation: ConversationSummaryApi, scope: ProjectScope | null): ChatListItem {
    return {
        id: `conversation:${conversation.id}`,
        kind: 'conversation',
        sourceId: conversation.id,
        title: titleOr(conversation.title, 'Untitled chat'),
        updatedAt: conversation.updated_at ?? conversation.created_at ?? '',
        status: null,
        pullRequestUrl: null,
        webUrl: aiWebUrl(scope, 'chat', conversation.id),
    }
}

/** Rows without a readable time sort last. Zero instead of -Infinity keeps the comparator from returning NaN. */
function sortTime(item: ChatListItem): number {
    const time = Date.parse(item.updatedAt)
    return Number.isNaN(time) ? 0 : time
}

/**
 * Merges PostHog AI chats and sandbox sessions into one list, newest first. A chat that handed off to a listed
 * session is left out, because the session row already stands for that work.
 */
export function chatListFromSources(input: {
    conversations: ConversationSummaryApi[] | undefined
    sessions: TaskSummaryApi[] | undefined
    scope: ProjectScope | null
}): ChatListItem[] {
    const sessions = (input.sessions ?? []).filter((session) => !session.archived)
    const sessionIds = new Set(sessions.map((session) => session.id))
    const conversations = (input.conversations ?? []).filter(
        (conversation) => !conversation.task || !sessionIds.has(conversation.task.id)
    )
    const items = [
        ...sessions.map((session) => sessionItem(session, input.scope)),
        ...conversations.map((conversation) => conversationItem(conversation, input.scope)),
    ]
    return items.sort((a, b) => sortTime(b) - sortTime(a)).slice(0, CHAT_LIST_LIMIT)
}
