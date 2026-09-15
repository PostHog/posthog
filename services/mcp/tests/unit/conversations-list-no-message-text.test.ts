import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/conversations'
import type { Context } from '@/tools/types'

// A support message body carries whatever the customer pasted into it, including
// credentials and one-time links. A caller that lists tickets is choosing a ticket,
// so it gets the subject as a label and reads the thread only when it opens one.
describe('conversations-tickets-list keeps message bodies out of the list', () => {
    const ticket = {
        id: '019437a4-e72c-0000-0e20-a4ded5dfd02f',
        ticket_number: 412,
        status: 'open',
        priority: 'high',
        channel_source: 'email',
        assignee: null,
        email_subject: 'Cannot finish sign-in',
        last_message_text: 'Here is my reset link https://example.com/confirm?token=not-a-real-token',
        message_count: 3,
        unread_team_count: 1,
        created_at: '2026-09-01T10:00:00Z',
        updated_at: '2026-09-02T10:00:00Z',
    }

    function createContext(): Context {
        return {
            api: {
                request: vi.fn().mockResolvedValue({ count: 1, results: [ticket] }),
                getProjectBaseUrl: () => 'https://us.posthog.com/project/7',
            },
            stateManager: { getProjectId: async () => 7 },
            getDistinctId: async () => 'test-distinct-id',
            trackEvent: async () => {},
        } as unknown as Context
    }

    it('returns the subject but no message text', async () => {
        const result = (await GENERATED_TOOLS['conversations-tickets-list']!().handler(
            createContext(),
            {}
        )) as unknown as { results: Record<string, unknown>[] }

        const listed = result.results[0]!
        expect(listed.email_subject).toBe('Cannot finish sign-in')
        expect(listed).not.toHaveProperty('last_message_text')
    })
})
