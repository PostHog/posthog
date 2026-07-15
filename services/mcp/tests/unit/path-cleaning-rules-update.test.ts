import { describe, expect, it, vi } from 'vitest'

import type { Context } from '@/tools/types'
import updatePathCleaning, {
    applyOperations,
    normalizePathCleaningFilters,
    type PathCleaningRule,
    renumber,
    updatePathCleaningHandler,
} from '@/tools/projects/updatePathCleaning'

describe('normalizePathCleaningFilters', () => {
    it('sorts by order and drops entries missing alias or regex', () => {
        const raw = [
            { alias: '/b', regex: '/b/\\d+', order: 2 },
            { alias: '/a', regex: '/a/\\d+', order: 0 },
            { alias: '', regex: '/x', order: 1 },
            { alias: '/c', regex: '', order: 3 },
        ]
        expect(normalizePathCleaningFilters(raw)).toEqual([
            { alias: '/a', regex: '/a/\\d+', order: 0 },
            { alias: '/b', regex: '/b/\\d+', order: 2 },
        ])
    })

    it('falls back to array index when order is missing', () => {
        const raw = [
            { alias: '/first', regex: '/first' },
            { alias: '/second', regex: '/second' },
        ]
        expect(normalizePathCleaningFilters(raw).map((r) => r.alias)).toEqual(['/first', '/second'])
    })

    it('returns [] for non-array input', () => {
        expect(normalizePathCleaningFilters(undefined)).toEqual([])
        expect(normalizePathCleaningFilters(null)).toEqual([])
        expect(normalizePathCleaningFilters('nope')).toEqual([])
    })
})

describe('renumber', () => {
    it('assigns contiguous order 0..n-1', () => {
        const rules: PathCleaningRule[] = [
            { alias: '/a', regex: '/a' },
            { alias: '/b', regex: '/b' },
        ]
        expect(renumber(rules)).toEqual([
            { alias: '/a', regex: '/a', order: 0 },
            { alias: '/b', regex: '/b', order: 1 },
        ])
    })
})

describe('applyOperations', () => {
    const base: PathCleaningRule[] = [
        { alias: '/users/<id>', regex: '/users/\\d+' },
        { alias: '/signup/<id>', regex: '/signup/[0-9a-f-]+' },
    ]

    it('appends and inserts rules at the right positions', () => {
        const { rules } = applyOperations(base, [
            { action: 'append', alias: '/end', regex: '/end/\\d+' },
            { action: 'insert', index: 0, alias: '/start', regex: '/start/\\d+' },
        ])
        expect(rules.map((r) => r.alias)).toEqual(['/start', '/users/<id>', '/signup/<id>', '/end'])
    })

    it('clamps an out-of-range insert index to the end', () => {
        const { rules } = applyOperations(base, [{ action: 'insert', index: 99, alias: '/z', regex: '/z' }])
        expect(rules[rules.length - 1]!.alias).toBe('/z')
    })

    it('replaces an existing rule while keeping its position, preserving omitted fields', () => {
        const { rules } = applyOperations(base, [
            { action: 'replace', target_alias: '/signup/<id>', regex: '^/signup/[^/]+$' },
        ])
        expect(rules[1]).toEqual({ alias: '/signup/<id>', regex: '^/signup/[^/]+$' })
    })

    it('removes a rule by alias', () => {
        const { rules } = applyOperations(base, [{ action: 'remove', target_alias: '/users/<id>' }])
        expect(rules.map((r) => r.alias)).toEqual(['/signup/<id>'])
    })

    it('reorders when given a permutation of current aliases', () => {
        const { rules } = applyOperations(base, [
            { action: 'reorder', ordered_aliases: ['/signup/<id>', '/users/<id>'] },
        ])
        expect(rules.map((r) => r.alias)).toEqual(['/signup/<id>', '/users/<id>'])
    })

    it('throws on replace/remove of an unknown alias', () => {
        expect(() => applyOperations(base, [{ action: 'remove', target_alias: '/nope' }])).toThrow(/no rule with alias/)
        expect(() => applyOperations(base, [{ action: 'replace', target_alias: '/nope', regex: '/x' }])).toThrow(
            /no rule with alias/
        )
    })

    it('throws when reorder is not a permutation', () => {
        expect(() => applyOperations(base, [{ action: 'reorder', ordered_aliases: ['/users/<id>'] }])).toThrow(
            /must be exactly the current aliases/
        )
    })

    it('throws on an invalid regex before anything is saved', () => {
        expect(() => applyOperations(base, [{ action: 'append', alias: '/bad', regex: '/users/(' }])).toThrow(
            /Invalid regex/
        )
    })

    it('does not mutate the input array', () => {
        applyOperations(base, [{ action: 'remove', target_alias: '/users/<id>' }])
        expect(base.map((r) => r.alias)).toEqual(['/users/<id>', '/signup/<id>'])
    })
})

function createMockContext(overrides: {
    currentFilters: unknown
    getMock?: ReturnType<typeof vi.fn>
    updateMock?: ReturnType<typeof vi.fn>
}): Context {
    const getMock =
        overrides.getMock ??
        vi.fn().mockResolvedValue({ success: true, data: { path_cleaning_filters: overrides.currentFilters } })
    const updateMock =
        overrides.updateMock ??
        vi.fn().mockImplementation(async ({ filters }: { filters: unknown }) => ({
            success: true,
            data: { path_cleaning_filters: filters },
        }))
    return {
        api: {
            projects: () => ({ get: getMock, updatePathCleaningFilters: updateMock }),
            getProjectBaseUrl: () => 'https://us.posthog.com/project/2',
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('2') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('path-cleaning-rules-update handler', () => {
    const current = [{ alias: '/signup/<id>', regex: '/signup/[0-9a-f-]+', order: 0 }]

    it('previews without saving when confirm is not set', async () => {
        const updateMock = vi.fn()
        const context = createMockContext({ currentFilters: current, updateMock })

        const result = await updatePathCleaningHandler(context, {
            operations: [{ action: 'append', alias: '/shared/<hash>', regex: '^/shared/[^/]+$' }],
            sample_paths: ['/shared/abc123'],
            confirm: false,
        })

        expect(updateMock).not.toHaveBeenCalled()
        expect(result.applied).toBe(false)
        expect(result.resulting_rules).toEqual([
            { alias: '/signup/<id>', regex: '/signup/[0-9a-f-]+', order: 0 },
            { alias: '/shared/<hash>', regex: '^/shared/[^/]+$', order: 1 },
        ])
        expect(result.sample_preview).toEqual([
            { path: '/shared/abc123', before: '/shared/abc123', after: '/shared/<hash>' },
        ])
    })

    it('saves the renumbered rules when confirm is true', async () => {
        const updateMock = vi.fn().mockImplementation(async ({ filters }: { filters: unknown }) => ({
            success: true,
            data: { path_cleaning_filters: filters },
        }))
        const context = createMockContext({ currentFilters: current, updateMock })

        const result = await updatePathCleaningHandler(context, {
            operations: [
                { action: 'append', alias: '/embedded/<hash>', regex: '^/embedded/[^/]+$' },
                { action: 'remove', target_alias: '/signup/<id>' },
            ],
            confirm: true,
        })

        expect(updateMock).toHaveBeenCalledOnce()
        expect(updateMock.mock.calls[0]![0].filters).toEqual([
            { alias: '/embedded/<hash>', regex: '^/embedded/[^/]+$', order: 0 },
        ])
        expect(result.applied).toBe(true)
    })

    it('surfaces a read failure without attempting a write', async () => {
        const updateMock = vi.fn()
        const getMock = vi.fn().mockResolvedValue({ success: false, error: new Error('boom') })
        const context = createMockContext({ currentFilters: current, getMock, updateMock })

        await expect(
            updatePathCleaningHandler(context, {
                operations: [{ action: 'remove', target_alias: '/signup/<id>' }],
                confirm: true,
            })
        ).rejects.toThrow(/Failed to read current path cleaning rules: boom/)
        expect(updateMock).not.toHaveBeenCalled()
    })

    it('exposes the expected tool name', () => {
        expect(updatePathCleaning().name).toBe('path-cleaning-rules-update')
    })
})
