import { describe, expect, it } from 'vitest'

import { isRegexPattern, type SearchableTool, searchToolsRanked, searchToolsRegex } from '@/tools/tool-search'

const TOOLS: SearchableTool[] = [
    { name: 'dashboard-create', title: 'Create dashboard', description: 'Create a new dashboard' },
    { name: 'dashboard-get-all', title: 'List dashboards', description: 'List all dashboards in the project' },
    { name: 'insight-create', title: 'Create insight', description: 'Create a new insight (graph/trend)' },
    { name: 'insight-get-all', title: 'List insights', description: 'List all insights' },
    { name: 'feature-flag-get-all', title: 'List feature flags', description: 'List all feature flags' },
    { name: 'query-run', title: 'Run query', description: 'Run an arbitrary HogQL query' },
    { name: 'experiment-create', title: 'Create experiment', description: 'Create a new experiment' },
]

describe('tool-search', () => {
    describe('searchToolsRanked', () => {
        it('surfaces the relevant create tools for a multi-word natural-language query', () => {
            // The original single-regex predicate returned ZERO for this phrase —
            // this is the regression the forgiving search exists to fix.
            const ranked = searchToolsRanked(TOOLS, 'create dashboard insight')
            expect(ranked.length).toBeGreaterThan(0)
            expect(ranked.slice(0, 2).map((r) => r.name)).toEqual(['dashboard-create', 'insight-create'])
        })

        it('weights a name hit above a token that only appears in prose', () => {
            // "experiment-create" matches two tokens in its name; tools that merely
            // mention "create" elsewhere must not outrank it.
            const ranked = searchToolsRanked(TOOLS, 'create experiment')
            expect(ranked[0]?.name).toBe('experiment-create')
        })

        it('returns nothing when no token matches any field', () => {
            expect(searchToolsRanked(TOOLS, 'nonexistent-token')).toEqual([])
        })
    })

    describe('searchToolsRegex', () => {
        it('matches a kebab-case prefix pattern against name/title/description', () => {
            expect(searchToolsRegex(TOOLS, 'query-').map((t) => t.name)).toEqual(['query-run'])
        })

        it('matches every feature-flag tool', () => {
            expect(searchToolsRegex(TOOLS, 'feature-flag').map((t) => t.name)).toEqual(['feature-flag-get-all'])
        })

        it('throws on an invalid regex so callers can surface their own message', () => {
            expect(() => searchToolsRegex(TOOLS, '[invalid')).toThrow(/regular expression/i)
        })
    })

    describe('isRegexPattern', () => {
        it('treats kebab-case and regex patterns as regex', () => {
            expect(isRegexPattern('query-')).toBe(true)
            expect(isRegexPattern('feature-flag')).toBe(true)
            expect(isRegexPattern('a|b')).toBe(true)
            expect(isRegexPattern('get.*')).toBe(true)
        })

        it('treats plain words as non-regex so they route to ranked search', () => {
            expect(isRegexPattern('dashboard')).toBe(false)
            expect(isRegexPattern('create dashboard insight')).toBe(false)
        })
    })
})
