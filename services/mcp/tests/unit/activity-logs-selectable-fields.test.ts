import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/platform_features'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

// One full-fat activity entry carrying every field the tool's `response.include` allowlist keeps,
// so a narrowing bug (fields ignored -> full payload) is visible.
const FULL_ENTRY = {
    id: 'abc',
    user: { id: 7, first_name: 'Ada', last_name: 'Lovelace', email: 'ada@posthog.com' },
    activity: 'updated',
    scope: 'FeatureFlag',
    item_id: '42',
    detail: {
        name: 'my-flag',
        short_id: 'AB12',
        type: 'boolean',
        changes: [{ field: 'active', before: false, after: true }],
    },
    created_at: '2026-07-13T00:00:00Z',
    // A field outside the allowlist — must never survive projection.
    unredacted_ip: '10.0.0.1',
}

function mockContext(): Context {
    return {
        stateManager: { getProjectId: async () => 1 },
        api: {
            getProjectBaseUrl: () => 'https://us.posthog.com/project/1',
            request: async () => ({ count: 1, next: null, previous: null, results: [FULL_ENTRY] }),
        },
    } as unknown as Context
}

describe('advanced-activity-logs-list selectable fields', () => {
    const listTool = GENERATED_TOOLS['advanced-activity-logs-list'] as () => ToolBase<ZodObjectAny>

    it('narrows each result to the requested fields when `fields` is passed', async () => {
        const result: any = await listTool().handler(mockContext(), {
            fields: ['user.email', 'activity', 'created_at'],
        })
        const [entry] = result.results

        expect(entry).toEqual({
            user: { email: 'ada@posthog.com' },
            activity: 'updated',
            created_at: '2026-07-13T00:00:00Z',
        })
        // The heavy diff branch is dropped when not requested.
        expect(entry).not.toHaveProperty('detail')
    })

    it('returns the full allowlist (including detail.changes) when `fields` is omitted', async () => {
        const result: any = await listTool().handler(mockContext(), {})
        const [entry] = result.results

        expect(entry.detail.changes).toEqual([{ field: 'active', before: false, after: true }])
        expect(entry.user.email).toBe('ada@posthog.com')
        // Fields outside the allowlist are still filtered out regardless of `fields`.
        expect(entry).not.toHaveProperty('unredacted_ip')
    })

    it('constrains `fields` to the allowlist at the schema level', () => {
        const schema = listTool().schema

        expect(schema.safeParse({ fields: ['user.email', 'activity'] }).success).toBe(true)
        // A real response field that is not in the allowlist cannot be requested.
        expect(schema.safeParse({ fields: ['unredacted_ip'] }).success).toBe(false)
        // An empty array is rejected rather than silently falling back to the full payload.
        expect(schema.safeParse({ fields: [] }).success).toBe(false)
    })
})
