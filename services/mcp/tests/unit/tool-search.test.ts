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

        it('matches whole words, so "view" no longer hits "review", "overview" or "preview"', () => {
            const tools: SearchableTool[] = [
                { name: 'workflows-get', title: 'Get workflow', description: 'Get a workflow by ID' },
                { name: 'review-hog-reviews-trigger', title: 'Trigger review', description: 'Review the workflow' },
                { name: 'query-web-overview', title: 'Web overview', description: 'Overview of a workflow' },
            ]
            expect(searchToolsRanked(tools, 'view workflow')[0]?.name).toBe('workflows-get')
        })

        it('does not let "person" match "personal"', () => {
            const tools: SearchableTool[] = [
                { name: 'persons-retrieve', title: 'Get person', description: 'Get a person by ID' },
                { name: 'llma-personal-spend', title: 'Get my LLM spend', description: 'Personal LLM spend' },
            ]
            expect(searchToolsRanked(tools, 'personal').map((r) => r.name)).toEqual(['llma-personal-spend'])
            expect(searchToolsRanked(tools, 'person')[0]?.name).toBe('persons-retrieve')
        })

        it('folds plurals and common suffixes', () => {
            const tools: SearchableTool[] = [
                { name: 'feature-flag-get-all', title: 'Get all feature flags', description: 'List feature flags' },
                { name: 'annotation-create', title: 'Create annotation', description: 'Mark a deployment on charts' },
            ]
            expect(searchToolsRanked(tools, 'flag')[0]?.name).toBe('feature-flag-get-all')
            expect(searchToolsRanked(tools, 'annotate deploy')[0]?.name).toBe('annotation-create')
        })

        it('ignores filler words that used to score on nearly every description', () => {
            expect(searchToolsRanked(TOOLS, 'the a of')).toEqual([])
        })

        it('maps intent verbs onto API verbs, below the word that was actually typed', () => {
            const tools: SearchableTool[] = [
                { name: 'dashboard-delete', title: 'Delete dashboard', description: 'Delete a dashboard' },
                { name: 'dashboard-remove-tile', title: 'Remove dashboard tile', description: 'Remove a tile' },
                { name: 'dashboard-get', title: 'Get dashboard', description: 'Get a dashboard by ID' },
            ]
            // "remove" is typed: the tool that says "remove" wins, the "delete" tool still surfaces.
            expect(searchToolsRanked(tools, 'remove dashboard tile')[0]?.name).toBe('dashboard-remove-tile')
            expect(searchToolsRanked(tools, 'remove dashboard').map((r) => r.name)).toContain('dashboard-delete')
            expect(searchToolsRanked(tools, 'show dashboard')[0]?.name).toBe('dashboard-get')
        })

        it('finds person tools when the agent says "user"', () => {
            const tools: SearchableTool[] = [
                { name: 'persons-list', title: 'List persons', description: 'List persons, filterable by email' },
                { name: 'workflows-get-email-template', title: 'Get email template', description: 'Email template' },
            ]
            expect(searchToolsRanked(tools, 'find user by email')[0]?.name).toBe('persons-list')
        })

        it('counts a rare word for more than a common one', () => {
            const tools: SearchableTool[] = [
                { name: 'survey-stats', title: 'Get survey stats', description: 'Response statistics for a survey' },
                { name: 'experiment-results-get', title: 'Get experiment results', description: 'Experiment results' },
                { name: 'experiment-timeseries-results', title: 'Timeseries', description: 'Results over time' },
            ]
            // "results" is common, "survey" is rare: the survey tool must lead.
            expect(searchToolsRanked(tools, 'survey results')[0]?.name).toBe('survey-stats')
        })

        it('prefers the general tool when two tools match equally', () => {
            const tools: SearchableTool[] = [
                { name: 'experiment-get-by-flag-key', title: 'Get experiment', description: 'Get an experiment' },
                { name: 'experiment-get', title: 'Get experiment', description: 'Get an experiment' },
            ]
            expect(searchToolsRanked(tools, 'get experiment')[0]?.name).toBe('experiment-get')
        })

        it('reuses its index when tool objects are rebuilt from unchanged definitions', () => {
            const first = searchToolsRanked(TOOLS, 'list insights')
            const rebuilt = searchToolsRanked(
                TOOLS.map((t) => ({ ...t })),
                'list insights'
            )
            expect(rebuilt).toEqual(first)
            // A changed description is re-indexed, not served stale: once "HogQL" is gone
            // from the only tool that mentioned it, searching for it finds nothing.
            expect(searchToolsRanked(TOOLS, 'hogql').map((r) => r.name)).toEqual(['query-run'])
            const changed = TOOLS.map((t) => (t.name === 'query-run' ? { ...t, description: 'Run a saved report' } : t))
            expect(searchToolsRanked(changed, 'hogql')).toEqual([])
            expect(searchToolsRanked(changed, 'saved report')[0]?.name).toBe('query-run')
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
