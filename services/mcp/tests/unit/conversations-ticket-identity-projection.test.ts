import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/conversations'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

// The debugging-feature-flags skill gates every project read on `identity_verified`, and
// the retrieve tool answers through an allowlist projection. Drop the field from the
// allowlist and the serializer tests stay green while the gate loses its only signal.
// The integration suite cannot hold this: it runs against whatever tickets the project
// happens to have, and the CI project has none.
const TICKET = {
    id: '0199f3b2-0000-7000-8000-000000000001',
    ticket_number: 42,
    status: 'open',
    channel_source: 'email',
    email_from: 'robin@example.com',
    identity_verified: false,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    // Outside the allowlist, so it proves the projection ran at all. Without it a passing
    // `identity_verified` assertion could just mean nothing was filtered.
    slack_channel_id: 'C0123456789',
}

function mockContext(): Context {
    return {
        stateManager: { getProjectId: async () => 1 },
        api: {
            getProjectBaseUrl: () => 'https://us.posthog.com/project/1',
            request: async () => TICKET,
        },
    } as unknown as Context
}

describe('conversations-tickets-retrieve response projection', () => {
    const tool = GENERATED_TOOLS['conversations-tickets-retrieve'] as () => ToolBase<ZodObjectAny>

    it('keeps identity_verified and drops the fields agents do not read', async () => {
        const result: any = await tool().handler(mockContext(), { id: TICKET.id })
        const data = result.data ?? result

        expect(data.identity_verified).toBe(false)
        expect(data.email_from).toBe('robin@example.com')
        expect(data).not.toHaveProperty('slack_channel_id')
    })
})
