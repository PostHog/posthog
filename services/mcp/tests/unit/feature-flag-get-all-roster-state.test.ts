import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

// A disabled flag whose only release condition serves nobody. The list serializer reports
// `status: "ACTIVE"` for it, because `status` is a staleness verdict and staleness is only
// measured on enabled flags.
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

// An alpha early access flag. Its only release condition sits at 0%, but the matcher serves every
// person who opted in before it reads any release condition.
const EARLY_ACCESS_FLAG = {
    ...DISABLED_FLAG,
    id: 43,
    key: 'new-dashboard-beta',
    name: 'New dashboard beta',
    active: true,
    filters: { ...DISABLED_FLAG.filters, feature_enrollment: true },
}

const listContext = (flag: Record<string, unknown>): Context =>
    ({
        api: {
            request: vi.fn().mockResolvedValue({ count: 1, results: [flag] }),
            getProjectBaseUrl: () => 'https://app.posthog.com/project/17',
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
    }) as unknown as Context

const listOneFlag = async (flag: Record<string, unknown> = DISABLED_FLAG): Promise<Record<string, any>> => {
    const result = (await GENERATED_TOOL_MAP['feature-flag-get-all']!().handler(listContext(flag), {})) as {
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

    it('carries early access enrollment, so an enrolled flag at 0% does not read as serving nobody', async () => {
        const row = await listOneFlag(EARLY_ACCESS_FLAG)

        expect(row.filters).toEqual({ groups: [{ rollout_percentage: 0 }], feature_enrollment: true })
    })

    it('tells the agent that `status` is not the enabled state', () => {
        const description = getToolDefinition('feature-flag-get-all').description

        expect(description).toContain('Read whether a flag is on from `active`, never from `status`')
    })
})
