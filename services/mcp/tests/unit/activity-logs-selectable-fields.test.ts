import { describe, expect, it, vi } from 'vitest'

import { getToolsFromContext } from '@/tools'
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

    it.each(['Team', 'FeatureFlag', 'Experiment', 'Survey'])(
        'lets a project-scoped scout query bounded %s history through the runtime catalog',
        async (scope) => {
            const context = mockContext()
            context.stateManager.getAiConsentGiven = async () => true
            context.stateManager.getApiKey = async () => ({
                scopes: ['activity_log:read', 'internal_run:read', 'signal_scout_internal:write'],
                scoped_teams: [1],
                scoped_organizations: [],
            })
            const request = vi.spyOn(context.api, 'request')
            const tools = await getToolsFromContext(context, {
                tools: ['advanced-activity-logs-list'],
                scopedTeams: [1],
                availableFeatures: ['audit_logs'],
                isCloud: true,
            })
            const tool = tools.find((candidate) => candidate.name === 'advanced-activity-logs-list')
            expect(tool).toBeTruthy()
            expect(tool!.annotations).toMatchObject({ readOnlyHint: true, destructiveHint: false })

            const query = {
                scopes: [scope],
                item_ids: ['42'],
                start_date: '2026-01-01T00:00:00Z',
                end_date: '2026-01-02T00:00:00Z',
                page_size: 10,
            }
            const params = tool!.schema.parse({ ...query, fields: ['activity', 'created_at'] })
            const result = await tool!.handler(context, params)

            expect(request).toHaveBeenCalledExactlyOnceWith({
                method: 'GET',
                path: '/api/projects/1/advanced_activity_logs/',
                query: expect.objectContaining(query),
            })
            expect(result).toMatchObject({
                results: [{ activity: 'updated', created_at: FULL_ENTRY.created_at }],
            })
            expect(result).not.toHaveProperty('results.0.detail')
        }
    )

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
