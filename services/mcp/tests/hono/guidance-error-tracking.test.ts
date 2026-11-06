import { describe, expect, it, vi } from 'vitest'

import { GuidanceEngine, type GuidanceCall } from '@/hono/guidance/engine'
import {
    MCP_GUIDANCE_ERROR_TRACKING_EMPTY_FILTERS_FLAG,
    MCP_GUIDANCE_ERROR_TRACKING_EMPTY_RANGE_FLAG,
    MCP_GUIDANCE_ERROR_TRACKING_EMPTY_SETUP_FLAG,
} from '@/hono/guidance/rules'
import type { ResolvedState } from '@/hono/request-state-resolver'

import { makeToolExecutorState } from '../shared/test-utils'
import { makeGuidanceRedis } from './helpers/guidance-redis-stubs'

const ALL_FLAGS = {
    [MCP_GUIDANCE_ERROR_TRACKING_EMPTY_SETUP_FLAG]: true,
    [MCP_GUIDANCE_ERROR_TRACKING_EMPTY_FILTERS_FLAG]: true,
    [MCP_GUIDANCE_ERROR_TRACKING_EMPTY_RANGE_FLAG]: true,
}

function emptyList(args: Record<string, unknown> = {}): GuidanceCall {
    return { toolName: 'query-error-tracking-issues-list', args, isError: false, resultEmpty: true }
}

function makeState(
    options: {
        project?: () => Promise<unknown>
        request?: () => Promise<unknown>
        flags?: Record<string, boolean>
    } = {}
): {
    state: ResolvedState
    getProject: ReturnType<typeof vi.fn>
    request: ReturnType<typeof vi.fn>
} {
    const state = makeToolExecutorState([{ name: 'query-error-tracking-issues-list' }, { name: 'docs-search' }], {
        suppressAnalytics: false,
        toolFeatureFlags: options.flags ?? ALL_FLAGS,
    })
    const getProject = vi.fn(options.project ?? (async () => ({ ingested_event: true })))
    const request = vi.fn(options.request ?? (async () => ({ exists: true })))
    state.context.stateManager = {
        getCachedOrFetchProject: getProject,
        getProjectId: vi.fn().mockResolvedValue('42'),
    } as any
    state.context.api = { request } as any
    return { state, getProject, request }
}

describe('error tracking empty-result guidance', () => {
    it.each([
        ['a project with no data', { ingested_event: false }, { exists: true }, {}, undefined],
        ['a later page', { ingested_event: true }, { exists: true }, { offset: 10 }, undefined],
        ['the first page at offset 0', { ingested_event: true }, { exists: true }, { offset: 0 }, 'range'],
        ['a project with no issues', { ingested_event: true }, { exists: false }, {}, 'setup'],
        ['filters on a project with no issues', { ingested_event: true }, { exists: false }, { url: 'a' }, 'setup'],
        ['a narrowing filter', { ingested_event: true }, { exists: true }, { searchQuery: 'x' }, 'filters'],
        [
            'status and an empty filter group',
            { ingested_event: true },
            { exists: true },
            { status: 'all', filterGroup: [] },
            'range',
        ],
    ])('handles %s', async (_label, project, exists, args, expected) => {
        const { state } = makeState({ project: async () => project, request: async () => exists })
        const notice = await new GuidanceEngine(makeGuidanceRedis()).evaluate(state, emptyList(args))
        expect(notice?.ruleId).toBe(expected && `error-tracking-empty-to-${expected}`)
    })

    it('names the filters the call used and no others', async () => {
        const { state } = makeState()
        const notice = await new GuidanceEngine(makeGuidanceRedis()).evaluate(
            state,
            emptyList({ searchQuery: 'secret-value', library: 'posthog-js', status: 'active' })
        )
        expect(notice?.text).toContain('`searchQuery`, `library`')
        expect(notice?.text).not.toContain('secret-value')
        expect(notice?.text).not.toContain('`status`')
    })

    it('skips the issue lookup for a project with no data', async () => {
        const { state, request } = makeState({ project: async () => ({ ingested_event: false }) })
        await new GuidanceEngine(makeGuidanceRedis()).evaluate(state, emptyList())
        expect(request).not.toHaveBeenCalled()
    })

    it('ignores a populated result without reading product state', async () => {
        const { state, getProject } = makeState()
        const notice = await new GuidanceEngine(makeGuidanceRedis()).evaluate(state, {
            ...emptyList(),
            resultEmpty: false,
        })
        expect(notice).toBeUndefined()
        expect(getProject).not.toHaveBeenCalled()
    })

    it('stamps flag_off without text after the same checks', async () => {
        const { state, request } = makeState({ flags: {} })
        await expect(new GuidanceEngine(makeGuidanceRedis()).evaluate(state, emptyList())).resolves.toEqual({
            ruleId: 'error-tracking-empty-to-range',
            outcome: 'flag_off',
        })
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('repeats neither the notice nor the API lookup once the session reaches the cap', async () => {
        const { state, request } = makeState()
        const engine = new GuidanceEngine(makeGuidanceRedis())
        await engine.evaluate(state, emptyList())
        await expect(engine.evaluate(state, emptyList())).resolves.toBeUndefined()
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('shows the filters notice at most twice in a session', async () => {
        const { state } = makeState()
        const engine = new GuidanceEngine(makeGuidanceRedis())
        const call = emptyList({ library: 'posthog-js' })
        const notices = [
            await engine.evaluate(state, call),
            await engine.evaluate(state, call),
            await engine.evaluate(state, call),
        ]
        expect(notices.map((notice) => notice?.outcome)).toEqual(['shown', 'shown', undefined])
    })

    it('reports a suppressed setup notice after the session searched the docs', async () => {
        const { state } = makeState({ request: async () => ({ exists: false }) })
        const engine = new GuidanceEngine(makeGuidanceRedis())
        await engine.evaluate(state, { toolName: 'docs-search', args: {}, isError: false })
        await expect(engine.evaluate(state, emptyList())).resolves.toEqual({
            ruleId: 'error-tracking-empty-to-setup',
            outcome: 'suppressed',
        })
    })
})
