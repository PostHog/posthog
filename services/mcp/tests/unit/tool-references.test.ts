import { describe, expect, it } from 'vitest'

import { checkReferencesInText, type Violation } from '../../scripts/lib/tool-references'

const TOOLS = new Set([
    'execute-sql',
    'experiment-ship-variant',
    'feature-flag-get-all',
    'external-data-schemas-partial-update',
    'read-data-schema',
    'signals-scout-runs-list',
])
const SKILLS = new Set(['finding-experiments', 'creating-experiments'])

function flagged(text: string): Violation[] {
    const violations: Violation[] = []
    checkReferencesInText(text, 'test', TOOLS, SKILLS, new Set(), violations)
    return violations
}

describe('checkReferencesInText', () => {
    it.each([
        // [description, text, expected flagged names]
        [
            'renamed tool (near-miss)',
            'search flags with the feature-flags-get-all tool first',
            ['feature-flags-get-all'],
        ],
        [
            'fictional snake_case tool in backticks',
            'Use the `experiment_results_summary` tool',
            ['experiment_results_summary'],
        ],
        ['snake_case in plural phrase', 'use the launch, end, or ship_variant tools instead', ['ship_variant']],
        ['wrong casing', '`execute_sql`: query the experiments table', ['execute_sql']],
        ['one report when phrase and casing rules overlap', 'use the `execute_sql` tool', ['execute_sql']],
        ['nonexistent skill in backticks', 'load the `managing-unicorns` skill first', ['managing-unicorns']],
        ['renamed skill (near-miss)', 'load the finding-experiment skill first', ['finding-experiment']],
        ['invocation of unknown tool', 'query it via `does-not-exist-here`', ['does-not-exist-here']],
        ['exact tool name', 'use the read-data-schema tool to discover events', []],
        ['suffix shorthand', 'change the sync type with the `partial-update` tool', []],
        ['plural family reference', 'browse with the feature-flag tools', []],
        ['bare prose adjective (per-file)', 'this is a per-file tool for editing', []],
        ['bare prose adjective (highest-error)', 'rank by the highest-error tool first', []],
        ['capitalized prose does not match mid-word', 'Deep-dive skills are useful here', []],
        ['entity noun after backticks', 'teams enrolled via the `signals-scout` feature flag', []],
        ['existing skill', 'load the finding-experiments skill first', []],
        ['skill name in invocation context', 'resolve the reference via `creating-experiments`', []],
    ])('%s', (_description, text, expectedNames) => {
        expect(flagged(text).map((v) => v.tool)).toEqual(expectedNames)
    })

    it.each([
        [
            'suffix and casing matches',
            'use the launch or ship_variant tools instead',
            'did you mean experiment-ship-variant',
        ],
        [
            'bare near-miss rename',
            'search flags with the feature-flags-get-all tool first',
            'did you mean feature-flag-get-all',
        ],
    ])('suggests the real tool for %s', (_description, text, expectedSuggestion) => {
        const [violation] = flagged(text)
        expect(violation?.reason).toContain(expectedSuggestion)
    })

    it('dedupes repeated violations across texts via the shared seen set', () => {
        const violations: Violation[] = []
        const seen = new Set<string>()
        checkReferencesInText('use the feature-flags-get-all tool', 'a', TOOLS, SKILLS, seen, violations)
        checkReferencesInText('use the feature-flags-get-all tool', 'b', TOOLS, SKILLS, seen, violations)
        expect(violations).toHaveLength(1)
        expect(violations[0]?.source).toBe('a')
    })
})
