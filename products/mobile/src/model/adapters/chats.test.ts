import type { ConversationSummaryApi } from '@/api/conversations'
import type { TaskRunStatusApi, TaskSummaryApi } from '@/api/tasks'

import type { ChatSessionStatus } from '../types'
import { chatListFromSources } from './chats'

const scope = { host: 'https://us.posthog.com', projectId: 7 }

function conversation(overrides: Partial<ConversationSummaryApi> = {}): ConversationSummaryApi {
    return {
        id: 'c1',
        status: 'idle',
        title: 'Why did signups drop?',
        created_at: '2026-10-10T08:00:00Z',
        updated_at: '2026-10-10T09:00:00Z',
        type: 'assistant',
        task: null,
        ...overrides,
    }
}

function session(overrides: Partial<TaskSummaryApi> = {}): TaskSummaryApi {
    return {
        id: 't1',
        title: 'Fix the flaky test',
        archived: false,
        latest_run: { status: 'completed', output: null },
        created_at: '2026-10-10T07:00:00Z',
        updated_at: '2026-10-10T07:30:00Z',
        last_activity_at: '2026-10-10T10:00:00Z',
        ...overrides,
    }
}

describe('chatListFromSources', () => {
    test('merges both sources newest first and links each row to the web app', () => {
        const items = chatListFromSources({
            conversations: [conversation({ id: 'c1', updated_at: '2026-10-10T09:00:00Z' })],
            sessions: [
                session({
                    id: 't1',
                    last_activity_at: '2026-10-10T10:00:00Z',
                    latest_run: { status: 'completed', output: { pr_urls: ['https://github.com/example/app/pull/1'] } },
                }),
                session({ id: 't2', last_activity_at: null, updated_at: null, created_at: '2026-10-09T10:00:00Z' }),
            ],
            scope,
        })
        expect(items).toEqual([
            {
                id: 'session:t1',
                kind: 'session',
                sourceId: 't1',
                title: 'Fix the flaky test',
                updatedAt: '2026-10-10T10:00:00Z',
                status: 'completed',
                pullRequestUrl: 'https://github.com/example/app/pull/1',
                webUrl: 'https://us.posthog.com/project/7/ai?task=t1',
            },
            {
                id: 'conversation:c1',
                kind: 'conversation',
                sourceId: 'c1',
                title: 'Why did signups drop?',
                updatedAt: '2026-10-10T09:00:00Z',
                status: null,
                pullRequestUrl: null,
                webUrl: 'https://us.posthog.com/project/7/ai?chat=c1',
            },
            expect.objectContaining({ id: 'session:t2', updatedAt: '2026-10-09T10:00:00Z' }),
        ])
    })

    test('drops archived sessions and chats that handed off to a listed session', () => {
        const items = chatListFromSources({
            conversations: [
                conversation({ id: 'linked', task: { id: 't1' } }),
                conversation({ id: 'linked-to-archived', task: { id: 't-archived' } }),
            ],
            sessions: [session({ id: 't1' }), session({ id: 't-archived', archived: true })],
            scope: null,
        })
        expect(items.map((item) => item.id)).toEqual(['session:t1', 'conversation:linked-to-archived'])
        expect(items.every((item) => item.webUrl === undefined)).toBe(true)
    })

    test('falls back to a placeholder title when the server has none', () => {
        const items = chatListFromSources({
            conversations: [conversation({ title: null })],
            sessions: [session({ title: '  ' })],
            scope,
        })
        expect(items.map((item) => item.title)).toEqual(['Untitled session', 'Untitled chat'])
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
        const [item] = chatListFromSources({ conversations: undefined, sessions: [session({ latest_run })], scope })
        expect(item?.status).toBe(expected)
    })

    test('keeps the newest 30 rows', () => {
        const conversations = Array.from({ length: 40 }, (_, index) =>
            conversation({ id: `c${index}`, updated_at: new Date(Date.UTC(2026, 9, 1, 0, index)).toISOString() })
        )
        const items = chatListFromSources({ conversations, sessions: undefined, scope })
        expect(items).toHaveLength(30)
        expect(items[0]?.sourceId).toBe('c39')
        expect(items[29]?.sourceId).toBe('c10')
    })
})
