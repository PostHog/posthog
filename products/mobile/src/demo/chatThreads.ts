import type { ConversationDetail, ConversationMessage } from '@/api/conversations'

interface DemoThread {
    id: string
    title: string
    /** Alternating turns, starting with the person's question. */
    turns: readonly string[]
}

const THREADS: readonly DemoThread[] = [
    {
        id: 'demo-chat-signup-drop',
        title: 'Why did signups drop on Tuesday?',
        turns: [
            'Why did signups drop on Tuesday?',
            'Signups fell about 30% on Tuesday. Most of the drop came from **mobile Safari**:\n\n- The signup form stopped submitting after the 2.14 release\n- Desktop signups stayed flat\n\nThe fix shipped on Wednesday morning, and signups recovered by the afternoon.',
            'Did we lose those people for good?',
            'About a third of the people who saw the error came back and signed up within two days. The rest have not returned yet.',
        ],
    },
    {
        id: 'demo-chat-checkout-errors',
        title: 'Checkout errors by browser',
        turns: [
            'Break down checkout errors by browser for the last 7 days',
            'Checkout errors in the last 7 days:\n\n- **Firefox**: 212\n- **Chrome**: 64\n- **Safari**: 41\n\nMost Firefox errors are `TypeError: plan is undefined` on the upgrade step.',
        ],
    },
    {
        id: 'demo-chat-weekly-summary',
        title: 'Summarize this week',
        turns: [
            'Summarize this week for the team',
            '**This week in Hedgebox**\n\n- 1,240 new signups, up 8% on last week\n- Shared folder uploads reached a new high on Thursday\n- Two reports need a decision: the upload retry bug and the pricing page drop',
            'Make it shorter',
            'Signups up 8%. Record folder uploads on Thursday. Two reports need a decision.',
        ],
    },
    {
        id: 'demo-chat-retention',
        title: 'Retention for the new onboarding',
        turns: [
            'How is week 1 retention for people who saw the new onboarding?',
            'Week 1 retention is **42%** with the new onboarding and **35%** with the old one. The gap holds on every plan.',
            'Is that enough data to trust?',
            'Each group has more than 2,000 people, so the difference is unlikely to be noise. Give it one more week before you remove the old flow.',
        ],
    },
    {
        id: 'demo-chat-status-update',
        title: 'Draft a status update for report load time',
        turns: [
            'Draft a status update for the report load time issue',
            '**Report load time**\n\nShared file reports took up to 9 seconds to load since Monday. The cause is a missing index on the file activity table. A fix is in review and ships tomorrow.',
        ],
    },
    {
        id: 'demo-chat-top-pages',
        title: 'Top pages last 30 days',
        turns: [
            'What were the top pages in the last 30 days?',
            'Top pages by views:\n\n1. `/files`: 48,200\n2. `/shared`: 21,900\n3. `/pricing`: 9,400\n4. `/settings/storage`: 6,100',
            'Which of those grew the most?',
            '`/shared` grew the most, up 24% on the 30 days before.',
        ],
    },
    {
        id: 'demo-chat-churn',
        title: 'Which accounts are at risk of churn?',
        turns: [
            'Which accounts are at risk of churn?',
            'Three team accounts uploaded nothing in the last 14 days, and two of them removed seats this month. I saved them in a cohort called **At-risk teams**.',
            'Who owns those accounts?',
            'None of them has an account owner set. Add owners in your CRM, then ask me again.',
        ],
    },
    {
        id: 'demo-chat-funnel',
        title: 'Funnel from pricing to paid',
        turns: [
            'Show the funnel from the pricing page to a paid plan',
            'Of the people who viewed `/pricing` in the last 30 days:\n\n- 18% started checkout\n- 11% finished checkout\n\nThe biggest drop is between picking a plan and the payment form.',
        ],
    },
]

function messageFor(threadId: string, content: string, index: number): ConversationMessage {
    const id = `${threadId}-m${index}`
    return index % 2 === 0 ? { type: 'human', content, id } : { type: 'ai', content, id }
}

/** A stored demo conversation, shaped like `GET conversations/:id/`. Undefined for an id the demo does not know. */
export function demoConversationDetail(conversationId: string): ConversationDetail | undefined {
    const thread = THREADS.find((candidate) => candidate.id === conversationId)
    if (!thread) {
        return undefined
    }
    return {
        id: thread.id,
        status: 'idle',
        title: thread.title,
        messages: thread.turns.map((content, index) => messageFor(thread.id, content, index)),
        // The server reports its default mode for a chat that never picked one.
        agent_mode: 'product_analytics',
    }
}
