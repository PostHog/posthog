import type { ChatListItem, ChatSessionStatus } from '@/model/types'

const HOUR_MS = 3_600_000
const DAY_MS = 24 * HOUR_MS

type DemoWhen = { hoursAgo: number } | { daysAgo: number } | { yesterdayAt: [hours: number, minutes: number] }

interface DemoChat {
    id: string
    title: string
    when: DemoWhen
    status?: ChatSessionStatus
    pullRequestUrl?: string
}

// `chatThreads.ts` looks these conversations up by id, so renaming an id here leaves its row without a thread.
const DEMO_CONVERSATIONS: DemoChat[] = [
    { id: 'demo-chat-signup-drop', title: 'Why did signups drop on Tuesday?', when: { hoursAgo: 2 } },
    { id: 'demo-chat-checkout-errors', title: 'Checkout errors by browser', when: { hoursAgo: 5 } },
    { id: 'demo-chat-weekly-summary', title: 'Summarize this week', when: { yesterdayAt: [16, 10] } },
    { id: 'demo-chat-retention', title: 'Retention for the new onboarding', when: { yesterdayAt: [9, 30] } },
    { id: 'demo-chat-status-update', title: 'Draft a status update for report load time', when: { daysAgo: 3 } },
    { id: 'demo-chat-top-pages', title: 'Top pages last 30 days', when: { daysAgo: 6 } },
    { id: 'demo-chat-churn', title: 'Which accounts are at risk of churn?', when: { daysAgo: 12 } },
    { id: 'demo-chat-funnel', title: 'Funnel from pricing to paid', when: { daysAgo: 40 } },
]

const DEMO_SESSIONS: DemoChat[] = [
    {
        id: 'demo-session-flaky-test',
        title: 'Fix the flaky checkout test',
        when: { hoursAgo: 1 },
        status: 'completed',
        pullRequestUrl: 'https://github.com/example/app/pull/482',
    },
    {
        id: 'demo-session-dark-mode',
        title: 'Add dark mode to settings',
        when: { yesterdayAt: [11, 0] },
        status: 'working',
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

function toItem(chat: DemoChat, kind: ChatListItem['kind'], anchor: Date): ChatListItem {
    return {
        id: `${kind}:${chat.id}`,
        kind,
        sourceId: chat.id,
        title: chat.title,
        updatedAt: resolveWhen(chat.when, anchor).toISOString(),
        status: kind === 'session' ? (chat.status ?? 'idle') : null,
        pullRequestUrl: chat.pullRequestUrl ?? null,
    }
}

export function buildDemoChatList(anchor: Date): ChatListItem[] {
    const items = [
        ...DEMO_CONVERSATIONS.map((chat) => toItem(chat, 'conversation', anchor)),
        ...DEMO_SESSIONS.map((chat) => toItem(chat, 'session', anchor)),
    ]
    return items.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
}
