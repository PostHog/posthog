import type { TaskRunStatusApi, TaskSummaryApi } from '@/api/tasks'
import type { ConversationMinimalApi } from '../../../../posthog_ai/frontend/generated/api.schemas'

import type { ChatOrigin, ChatSessionStatus } from '../types'
import { chatListFromSessions, mergeChatLists } from './chats'

const scope = { host: 'https://us.posthog.com', projectId: 7 }

function session(overrides: Partial<TaskSummaryApi> = {}): TaskSummaryApi {
    return {
        id: 't1',
        title: 'Fix the flaky test',
        archived: false,
        latest_run: { status: 'completed', output: null },
        created_at: '2026-10-10T07:00:00Z',
        updated_at: '2026-10-10T07:30:00Z',
        last_activity_at: '2026-10-10T10:00:00Z',
        origin_product: 'posthog_ai',
        ...overrides,
    }
}

describe('chatListFromSessions', () => {
    test('merges unlinked classic history and report tasks', () => {
        const conversations = [
            {
                id: 'classic-1',
                title: 'A classic chat',
                status: 'idle',
                updated_at: '2026-10-10T12:00:00Z',
                task: null,
            },
        ] as ConversationMinimalApi[]
        const items = mergeChatLists(
            [session({ id: 'report-task', origin_product: 'signal_report' })],
            conversations,
            scope
        )
        expect(items.map((item) => item.id)).toEqual(['conversation:classic-1', 'session:report-task'])
        expect(items[0]?.webUrl).toBe('https://us.posthog.com/project/7/ai?chat=classic-1')
    })

    test('lists sessions newest first and links each row to the web app', () => {
        const items = chatListFromSessions(
            [
                session({ id: 't2', last_activity_at: null, updated_at: null, created_at: '2026-10-09T10:00:00Z' }),
                session({
                    id: 't1',
                    last_activity_at: '2026-10-10T10:00:00Z',
                    latest_run: { status: 'completed', output: { pr_urls: ['https://github.com/example/app/pull/1'] } },
                }),
            ],
            scope
        )
        expect(items).toEqual([
            {
                id: 'session:t1',
                kind: 'session',
                sourceId: 't1',
                origin: 'chat',
                title: 'Fix the flaky test',
                updatedAt: '2026-10-10T10:00:00Z',
                status: 'completed',
                pullRequestUrl: 'https://github.com/example/app/pull/1',
                webUrl: 'https://us.posthog.com/project/7/ai?task=t1',
            },
            expect.objectContaining({ id: 'session:t2', updatedAt: '2026-10-09T10:00:00Z' }),
        ])
    })

    test('keeps linked conversations as task rows without requiring list runtime metadata', () => {
        const conversations = [{ id: 'linked-chat', task: { id: 't1' } }] as ConversationMinimalApi[]
        const items = mergeChatLists([session()], conversations, scope)
        expect(items).toHaveLength(1)
        expect(items[0]).toMatchObject({ kind: 'session', sourceId: 't1', status: 'completed' })
    })

    test('leaves the web link out without a project scope', () => {
        const [item] = chatListFromSessions([session()], null)
        expect(item?.webUrl).toBeUndefined()
    })

    test('falls back to a placeholder title when the server has none', () => {
        const [item] = chatListFromSessions([session({ title: '  ' })], scope)
        expect(item?.title).toBe('Untitled session')
    })

    test.each<[string, ChatOrigin]>([
        ['posthog_ai', 'chat'],
        ['signal_report', 'report'],
        ['slack', 'session'],
    ])('maps origin product %s to %s', (originProduct, expected) => {
        const [item] = chatListFromSessions([session({ origin_product: originProduct })], scope)
        expect(item?.origin).toBe(expected)
    })

    test.each<[TaskRunStatusApi | null, ChatSessionStatus]>([
        ['failed', 'failed'],
        ['in_progress', 'working'],
        ['queued', 'queued'],
        ['not_started', 'starting'],
        ['cancelled', 'stopped'],
        ['completed', 'completed'],
        [null, 'idle'],
    ])('maps run status %s to %s', (runStatus, expected) => {
        const latest_run = runStatus ? { status: runStatus, output: null } : null
        const [item] = chatListFromSessions([session({ latest_run })], scope)
        expect(item?.status).toBe(expected)
    })
})
