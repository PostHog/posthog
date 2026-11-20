import { describe, expect, it, vi } from 'vitest'

import updatePathCleaning, {
    applyOperations,
    normalizePathCleaningFilters,
    type PathCleaningRule,
    renumber,
    updatePathCleaningHandler,
} from '@/tools/projects/updatePathCleaning'
import type { Context } from '@/tools/types'

describe('normalizePathCleaningFilters', () => {
    it('preserves stored array order (not the order field) and drops only entries with no regex', () => {
        // The backend applies rules in array order and ignores `order`, so normalize must NOT
        // re-sort — doing so would silently resequence untouched rules on save. Order-field
        // values here are deliberately non-monotonic to prove no sorting happens.
        const raw = [
            { alias: '/b', regex: '/b/\\d+', order: 2 },
            { alias: '/a', regex: '/a/\\d+', order: 0 },
            { alias: '', regex: '\\?page=\\d+$', order: 1 }, // empty alias = delete matched text; valid
            { alias: '/c', regex: '', order: 3 }, // no regex = meaningless; dropped
        ]
        expect(normalizePathCleaningFilters(raw)).toEqual([
            { alias: '/b', regex: '/b/\\d+', order: 2 },
            { alias: '/a', regex: '/a/\\d+', order: 0 },
            { alias: '', regex: '\\?page=\\d+$', order: 1 },
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

    it('does not mutate the input array', () => {
        applyOperations(base, [{ action: 'remove', target_alias: '/users/<id>' }])
        expect(base.map((r) => r.alias)).toEqual(['/users/<id>', '/signup/<id>'])
    })

    // Aliases are not unique — these guard the duplicate-alias handling.
    const dupes: PathCleaningRule[] = [
        { alias: '/x', regex: '/x/a' },
        { alias: '/x', regex: '/x/b' },
        { alias: '/y', regex: '/y' },
    ]

    it('reorders duplicate-aliased rules without dropping any', () => {
        const { rules } = applyOperations(dupes, [{ action: 'reorder', ordered_aliases: ['/y', '/x', '/x'] }])
        // All three rules survive; same-alias rules keep their original relative order.
        expect(rules).toEqual([
            { alias: '/y', regex: '/y' },
            { alias: '/x', regex: '/x/a' },
            { alias: '/x', regex: '/x/b' },
        ])
    })

    it('rejects a reorder that would drop a duplicate-aliased rule', () => {
        // ["/y","/x"] has the right distinct aliases but the wrong multiset (2 vs 3 rules).
        expect(() => applyOperations(dupes, [{ action: 'reorder', ordered_aliases: ['/y', '/x'] }])).toThrow(
            /must be exactly the current aliases/
        )
    })

    it('rejects a reorder with a repeated alias beyond its real count', () => {
        expect(() =>
            applyOperations(base, [{ action: 'reorder', ordered_aliases: ['/users/<id>', '/users/<id>'] }])
        ).toThrow(/must be exactly the current aliases/)
    })

    it('refuses to replace or remove an ambiguous (duplicated) alias instead of guessing', () => {
        expect(() => applyOperations(dupes, [{ action: 'remove', target_alias: '/x' }])).toThrow(/ambiguous/)
        expect(() => applyOperations(dupes, [{ action: 'replace', target_alias: '/x', regex: '/z' }])).toThrow(
            /ambiguous/
        )
    })

    it('creates and targets an empty-alias (delete matched text) rule', () => {
        const created = applyOperations(
            [{ alias: '/x', regex: '/x' }],
            [{ action: 'append', alias: '', regex: '\\?page=\\d+$' }]
        )
        expect(created.rules).toEqual([
            { alias: '/x', regex: '/x' },
            { alias: '', regex: '\\?page=\\d+$' },
        ])
        // The empty-alias rule can then be targeted by "" for removal.
        const removed = applyOperations(created.rules, [{ action: 'remove', target_alias: '' }])
        expect(removed.rules).toEqual([{ alias: '/x', regex: '/x' }])
    })
})

function previewResponse(before: string[], after: string[]): unknown {
    return { success: true, data: { results: [[before, after]] } }
}

function createMockContext(overrides: {
    currentFilters: unknown
    getMock?: ReturnType<typeof vi.fn>
    updateMock?: ReturnType<typeof vi.fn>
    queryMock?: ReturnType<typeof vi.fn>
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
    const queryMock = overrides.queryMock ?? vi.fn()
    return {
        api: {
            projects: () => ({ get: getMock, updatePathCleaningFilters: updateMock }),
            insights: () => ({ query: queryMock }),
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
        const queryMock = vi.fn().mockResolvedValue(previewResponse(['/shared/abc123'], ['/shared/<hash>']))
        const context = createMockContext({ currentFilters: current, updateMock, queryMock })

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

    it('runs one HogQL query that chains the current and resulting rules in order, passing every input as a value', async () => {
        const existing = [{ alias: '/users/<id>', regex: '/users/[0-9]+', order: 0 }]
        const queryMock = vi.fn().mockResolvedValue(previewResponse(['/users/<id>'], ['/users/<id>/anon']))
        const context = createMockContext({ currentFilters: existing, queryMock })

        await updatePathCleaningHandler(context, {
            operations: [{ action: 'append', alias: '/users/<id>/anon', regex: "/users/<id>$') --" }],
            sample_paths: ['/users/42'],
            confirm: false,
        })

        expect(queryMock.mock.calls[0]![0]).toEqual({
            query: {
                kind: 'HogQLQuery',
                query:
                    'SELECT arrayMap(path -> replaceRegexpAll(path, {before_regex_0}, {before_alias_0}), {sample_paths}), ' +
                    'arrayMap(path -> replaceRegexpAll(replaceRegexpAll(path, {after_regex_0}, {after_alias_0}), {after_regex_1}, {after_alias_1}), {sample_paths})',
                values: {
                    sample_paths: ['/users/42'],
                    before_regex_0: '/users/[0-9]+',
                    before_alias_0: '/users/<id>',
                    after_regex_0: '/users/[0-9]+',
                    after_alias_0: '/users/<id>',
                    after_regex_1: "/users/<id>$') --",
                    after_alias_1: '/users/<id>/anon',
                },
            },
        })
    })

    it('surfaces a query failure from an invalid regex as a tool error', async () => {
        const queryMock = vi.fn().mockResolvedValue({
            success: false,
            error: new Error('Cannot compile the regular expression. Check RE2 syntax'),
        })
        const updateMock = vi.fn()
        const context = createMockContext({ currentFilters: [], queryMock, updateMock })

        await expect(
            updatePathCleaningHandler(context, {
                operations: [{ action: 'append', alias: '/bad', regex: '/users/(' }],
                sample_paths: ['/users/42'],
                confirm: true,
            })
        ).rejects.toThrow(
            'The sample_paths preview failed to run (Cannot compile the regular expression. Check RE2 syntax). Check that every regex is valid re2, or retry without sample_paths.'
        )
        expect(updateMock).not.toHaveBeenCalled()
    })

    it('leaves regex validation to the backend, so a backend-valid \\C pattern saves', async () => {
        const updateMock = vi.fn().mockImplementation(async ({ filters }: { filters: unknown }) => ({
            success: true,
            data: { path_cleaning_filters: filters },
        }))
        const context = createMockContext({ currentFilters: [], updateMock })

        await updatePathCleaningHandler(context, {
            operations: [{ action: 'append', alias: '/files/<blob>', regex: '/files/\\C+' }],
            confirm: true,
        })

        expect(updateMock.mock.calls[0]![0].filters).toEqual([
            { alias: '/files/<blob>', regex: '/files/\\C+', order: 0 },
        ])
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
