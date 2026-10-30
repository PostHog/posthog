import type { ChatListItem, ChatOrigin, ChatSessionStatus } from '@/model/types'

const HOUR_MS = 3_600_000
const DAY_MS = 24 * HOUR_MS

type DemoWhen = { hoursAgo: number } | { daysAgo: number } | { yesterdayAt: [hours: number, minutes: number] }

interface DemoSession {
    id: string
    title: string
    when: DemoWhen
    status: ChatSessionStatus
    origin?: ChatOrigin
    pullRequestUrl?: string
}

// `sessionThreads.ts` looks these sessions up by id, so renaming an id here leaves its row without a thread.
const DEMO_SESSIONS: DemoSession[] = [
    {
        id: 'demo-session-flaky-test',
        title: 'Fix the flaky checkout test',
        when: { hoursAgo: 1 },
        status: 'completed',
        origin: 'chat',
        pullRequestUrl: 'https://github.com/example/app/pull/482',
    },
    {
        id: 'demo-session-dark-mode',
        title: 'Add dark mode to settings',
        when: { yesterdayAt: [11, 0] },
        status: 'working',
        origin: 'chat',
    },
    { id: 'demo-session-webhooks', title: 'Migrate billing webhooks', when: { daysAgo: 4 }, status: 'failed' },
]

function resolveWhen(when: DemoWhen, anchor: Date): Date {
    if ('hoursAgo' in when) {
        return new Date(anchor.getTime() - when.hoursAgo * HOUR_MS)
    }
    if ('daysAgo' in when) {
        return new Date(anchor.getTime() - when.daysAgo * DAY_MS)
    }
    const [hours, minutes] = when.yesterdayAt
    return new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() - 1, hours, minutes)
}

function toItem(session: DemoSession, anchor: Date): ChatListItem {
    return {
        id: `session:${session.id}`,
        kind: 'session',
        sourceId: session.id,
        origin: session.origin ?? 'session',
        title: session.title,
        updatedAt: resolveWhen(session.when, anchor).toISOString(),
        status: session.status,
        pullRequestUrl: session.pullRequestUrl ?? null,
    }
}

export function buildDemoChatList(anchor: Date): ChatListItem[] {
    const items = DEMO_SESSIONS.map((session) => toItem(session, anchor))
    return items.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
}
