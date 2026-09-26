import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

// A disabled flag whose only release condition serves nobody. The list serializer reports
// `status: "ACTIVE"` for it, because `status` is a staleness verdict and staleness is not
// measured on a flag that serves nobody.
const DISABLED_FLAG = {
    id: 42,
    key: 'checkout-rewrite',
    name: 'Checkout rewrite',
    active: false,
    archived: false,
    deleted: false,
    status: 'ACTIVE',
    updated_at: '2026-09-01T00:00:00Z',
    tags: [],
    filters: {
        groups: [{ rollout_percentage: 0, properties: [{ key: 'email', value: 'a@example.com' }] }],
        payloads: { true: '{"secret":true}' },
    },
    created_by: { email: 'someone@example.com' },
}

const listContext = (): { context: Context; request: ReturnType<typeof vi.fn> } => {
    const request = vi.fn().mockResolvedValue({ count: 1, results: [DISABLED_FLAG] })
    return {
        request,
        context: {
            api: { request, getProjectBaseUrl: () => 'https://app.posthog.com/project/17' },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
        } as unknown as Context,
    }
}

const listOneFlag = async (): Promise<Record<string, any>> => {
    const { context } = listContext()
    const result = (await GENERATED_TOOL_MAP['feature-flag-get-all']!().handler(context, {})) as {
        results: Record<string, any>[]
    }
    return result.results[0]!
}

describe('feature-flag-get-all roster state', () => {
    // Without `active` on the row, the only state an agent can read is `status`, and `status`
    // says ACTIVE for a flag that is switched off. Agents then report a disabled flag as live,
    // disagreeing with `feature-flag-get-definition` and the scout project profile.
    it('carries the enabled and archived state, not just the staleness verdict', async () => {
        const row = await listOneFlag()

        expect(row.active).toBe(false)
        expect(row.archived).toBe(false)
        expect(row.status).toBe('ACTIVE')
    })

    it('carries each release condition rollout without its targeting or payloads', async () => {
        const row = await listOneFlag()

        expect(row.filters).toEqual({ groups: [{ rollout_percentage: 0 }] })
    })

    it('tells the agent that `status` is not the enabled state', () => {
        const description = getToolDefinition('feature-flag-get-all').description

        expect(description).toContain('Read whether a flag is on from `active`, never from `status`')
    })
})
