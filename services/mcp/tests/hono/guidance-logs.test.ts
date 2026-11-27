import { describe, expect, it, vi } from 'vitest'

import { MCP_GUIDANCE_EMPTY_STATES_FLAG } from '@/hono/guidance/empty-result-rule'
import { GuidanceEngine, type GuidanceCall } from '@/hono/guidance/engine'

import { makeToolExecutorState } from '../shared/test-utils'
import { makeGuidanceRedis } from './helpers/guidance-redis-stubs'

async function noticeFor(hasLogs: boolean, query: Record<string, unknown>): Promise<string | undefined> {
    const state = makeToolExecutorState([{ name: 'query-logs' }, { name: 'docs-search' }], {
        suppressAnalytics: false,
        toolFeatureFlags: { [MCP_GUIDANCE_EMPTY_STATES_FLAG]: true },
    })
    state.context.stateManager = {
        getCachedOrFetchProject: vi.fn(async () => ({ ingested_event: false })),
        getProjectId: vi.fn().mockResolvedValue('42'),
    } as any
    state.context.api = { request: vi.fn(async () => ({ hasLogs })) } as any
    const call: GuidanceCall = { toolName: 'query-logs', args: { query }, isError: false, resultEmpty: true }
    return (await new GuidanceEngine(makeGuidanceRedis()).evaluate(state, call))?.ruleId
}

describe('logs empty-result guidance', () => {
    it.each([
        ['a project with no logs', false, { searchTerm: 'timeout', serviceNames: ['api'] }, 'no-logs'],
        ['a search term with filters', true, { searchTerm: 'timeout', serviceNames: ['api'] }, 'no-match'],
        ['a date range only', true, { dateRange: { date_from: '-1h' }, serviceNames: [] }, 'no-match'],
        ['a later page', true, { serviceNames: ['api'], after: 'cursor' }, undefined],
    ])('handles %s', async (_label, hasLogs, query, expected) => {
        expect(await noticeFor(hasLogs, query)).toBe(expected && `logs-empty-to-${expected}`)
    })
})
