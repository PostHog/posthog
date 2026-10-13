import { buildDemoChatList } from './chats'
import { demoConversationDetail } from './chatThreads'

const CONVERSATIONS = buildDemoChatList(new Date(2026, 9, 7, 15, 0)).filter((item) => item.kind === 'conversation')

describe('demo chat threads', () => {
    test.each(CONVERSATIONS.map((item) => [item.sourceId, item.title]))(
        'the demo chats list row %s opens a stored thread with the same title',
        (sourceId, title) => {
            const detail = demoConversationDetail(sourceId)
            expect(detail?.title).toBe(title)
            expect(detail?.messages.length).toBeGreaterThanOrEqual(2)
        }
    )
})
