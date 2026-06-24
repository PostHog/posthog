import { describe, expect, it } from 'vitest'

import { checkReferencesInText, type ReferenceFinding } from '../../scripts/lib/tool-references'

const TOOLS = new Set([
    'execute-sql',
    'experiment-ship-variant',
    'feature-flag-get-all',
    'external-data-schemas-partial-update',
    'read-data-schema',
    'signals-scout-runs-list',
])
const SKILLS = new Set(['finding-experiments', 'creating-experiments'])

function flagged(text: string): ReferenceFinding[] {
    const findings: ReferenceFinding[] = []
    checkReferencesInText(text, 'test', TOOLS, SKILLS, new Set(), findings)
    return findings
}

describe('checkReferencesInText', () => {
    it.each([
        // [description, text, expected flagged names]
        [
            'renamed tool (near-miss)',
            'search flags with the feature-flags-get-all tool first',
            ['feature-flags-get-all'],
        ],
        ['renamed skill (near-miss)', 'load the finding-experiment skill first', ['finding-experiment']],
        ['snake_case in plural phrase', 'use the launch, end, or ship_variant tools instead', ['ship_variant']],
        ['wrong casing', '`execute_sql`: query the experiments table', ['execute_sql']],
        ['one finding when phrase and casing rules overlap', 'use the `execute_sql` tool', ['execute_sql']],
        // Backticks are not intent: a backticked name that resembles nothing real is left alone.
        ['fictional backticked tool, no resemblance', 'Use the `experiment_results_summary` tool', []],
        ['fictional backticked skill, no resemblance', 'load the `managing-unicorns` skill first', []],
        ['fictional invocation, no resemblance', 'query it via `does-not-exist-here`', []],
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
        expect(flagged(text).map((f) => f.name)).toEqual(expectedNames)
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
        const [finding] = flagged(text)
        expect(finding?.message).toContain(expectedSuggestion)
    })

    it('locates the finding on the offending line and column', () => {
        const [finding] = flagged('intro line\nsearch with the feature-flags-get-all tool here')
        expect(finding).toMatchObject({ line: 2, col: 17, name: 'feature-flags-get-all' })
    })

    it('dedupes repeated findings across texts via the shared seen set', () => {
        const findings: ReferenceFinding[] = []
        const seen = new Set<string>()
        checkReferencesInText('use the feature-flags-get-all tool', 'a', TOOLS, SKILLS, seen, findings)
        checkReferencesInText('use the feature-flags-get-all tool', 'b', TOOLS, SKILLS, seen, findings)
        expect(findings).toHaveLength(1)
        expect(findings[0]?.source).toBe('a')
    })
})
