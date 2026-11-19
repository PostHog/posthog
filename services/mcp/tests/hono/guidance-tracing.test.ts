import { describe, expect, it, vi } from 'vitest'

import { MCP_GUIDANCE_EMPTY_STATES_FLAG } from '@/hono/guidance/empty-result-rule'
import { GuidanceEngine, type GuidanceCall } from '@/hono/guidance/engine'

import { makeToolExecutorState } from '../shared/test-utils'
import { makeGuidanceRedis } from './helpers/guidance-redis-stubs'

async function noticeFor(
    toolName: string,
    hasSpans: boolean,
    args: Record<string, unknown>
): Promise<string | undefined> {
    const state = makeToolExecutorState(
        [
            { name: 'query-apm-spans' },
            { name: 'apm-services-list' },
            { name: 'apm-trace-get' },
            { name: 'apm-attribute-values-list' },
            { name: 'docs-search' },
        ],
        { suppressAnalytics: false, toolFeatureFlags: { [MCP_GUIDANCE_EMPTY_STATES_FLAG]: true } }
    )
    state.context.stateManager = {
        getCachedOrFetchProject: vi.fn(async () => ({ ingested_event: false })),
        getProjectId: vi.fn().mockResolvedValue('42'),
    } as any
    state.context.api = { request: vi.fn(async () => ({ hasSpans })) } as any
    const call: GuidanceCall = { toolName, args, isError: false, resultEmpty: true }
    const notice = await new GuidanceEngine(makeGuidanceRedis()).evaluate(state, call)
    return notice?.ruleId
}

describe('tracing empty-result guidance', () => {
    it.each([
        [
            'spans in a project with none',
            'query-apm-spans',
            false,
            { query: { traceId: 'a' } },
            'spans-empty-to-no-spans',
        ],
        [
            'services in a project with none',
            'apm-services-list',
            false,
            { search: 'api' },
            'services-empty-to-no-spans',
        ],
        [
            'spans with filters',
            'query-apm-spans',
            true,
            { query: { serviceNames: ['api'] } },
            'spans-empty-to-no-match',
        ],
        ['services with a search', 'apm-services-list', true, { search: 'api' }, 'services-empty-to-no-match'],
        [
            'a later page of spans',
            'query-apm-spans',
            true,
            { query: { serviceNames: ['api'], offset: 100 } },
            undefined,
        ],
    ])('handles %s', async (_label, tool, hasSpans, args, expected) => {
        expect(await noticeFor(tool, hasSpans, args)).toBe(expected && `tracing-${expected}`)
    })
})
