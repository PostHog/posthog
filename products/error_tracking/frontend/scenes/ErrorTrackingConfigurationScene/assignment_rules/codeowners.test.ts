import type { RoleType } from '~/types'

import {
    bestRoleMatch,
    findCodeownersErrors,
    groupByOwner,
    levenshtein,
    ownerMatchFragments,
    patternToSourceMatch,
    parseCodeowners,
    patternToSourceValue,
    splitOwner,
} from './codeowners'

function makeRole(name: string): RoleType {
    return { id: name.toLowerCase(), name } as RoleType
}

describe('codeowners helpers', () => {
    describe('parseCodeowners', () => {
        it('parses patterns and owners, skipping comments and blank lines', () => {
            const text = [
                '# Comment line',
                '',
                'products/error_tracking/** @posthog/error-tracking',
                'frontend/   @posthog/frontend  @alice',
                '   # indented comment',
                'no-owners-here',
            ].join('\n')

            expect(parseCodeowners(text)).toEqual([
                { pattern: 'products/error_tracking/**', owners: ['@posthog/error-tracking'] },
                { pattern: 'frontend/', owners: ['@posthog/frontend', '@alice'] },
            ])
        })

        it('returns nothing for empty or comment-only input', () => {
            expect(parseCodeowners('')).toEqual([])
            expect(parseCodeowners('# just a comment\n\n')).toEqual([])
        })
    })

    describe('groupByOwner', () => {
        it('accumulates every path per owner in first-seen order, de-duping patterns', () => {
            const entries = parseCodeowners(
                [
                    'a/** @team-x',
                    'b/** @team-y @team-x',
                    'a/** @team-x', // duplicate pattern for team-x
                ].join('\n')
            )

            expect(groupByOwner(entries)).toEqual([
                { owner: '@team-x', patterns: ['a/**', 'b/**'] },
                { owner: '@team-y', patterns: ['b/**'] },
            ])
        })
    })

    describe('patternToSourceValue', () => {
        it.each([
            ['products/error_tracking/**', 'products/error_tracking'],
            ['/frontend/', 'frontend'],
            ['docs/*', 'docs'],
            ['*.py', '.py'],
            ['**/*.tsx', '.tsx'],
            ['src/components/Button.tsx', 'src/components/Button.tsx'],
            ['*', ''],
        ])('translates %s to %s', (pattern, expected) => {
            expect(patternToSourceValue(pattern)).toBe(expected)
        })
    })

    describe('patternToSourceMatch', () => {
        it.each([
            ['products/error_tracking/**', { operator: 'regex', value: '(^|/)products/error_tracking/.*' }],
            ['frontend/*.tsx', { operator: 'regex', value: '(^|/)frontend/[^/]*\\.tsx' }],
            ['nodejs/src/cdp/', { operator: 'icontains', value: 'nodejs/src/cdp' }],
        ])('translates %s to a source match', (pattern, expected) => {
            expect(patternToSourceMatch(pattern)).toEqual(expected)
        })
    })

    describe('levenshtein', () => {
        it.each([
            ['', '', 0],
            ['abc', '', 3],
            ['', 'abc', 3],
            ['kitten', 'sitting', 3],
            ['frontend', 'frontend', 0],
        ])('distance(%s, %s) = %i', (a, b, expected) => {
            expect(levenshtein(a, b)).toBe(expected)
        })
    })

    describe('bestRoleMatch', () => {
        const roles = [makeRole('Frontend'), makeRole('Backend Team'), makeRole('Error Tracking')]

        it('matches an exact team name (ignoring @org prefix and case)', () => {
            expect(bestRoleMatch('@posthog/frontend', roles)?.role.name).toBe('Frontend')
        })

        it('matches a close team name with hyphens normalized', () => {
            expect(bestRoleMatch('@posthog/error-tracking', roles)?.role.name).toBe('Error Tracking')
        })

        it('returns null when nothing clears the threshold', () => {
            expect(bestRoleMatch('@posthog/data-warehouse', roles)).toBeNull()
        })

        it('returns null when there are no roles', () => {
            expect(bestRoleMatch('@posthog/frontend', [])).toBeNull()
        })
    })

    describe('ownerMatchFragments', () => {
        it('de-dupes and drops empty fragments', () => {
            expect(ownerMatchFragments(['products/error_tracking/**', 'products/error_tracking/api', '*'])).toEqual([
                '(^|/)products/error_tracking/.*',
                'products/error_tracking/api',
            ])
        })
    })

    describe('findCodeownersErrors', () => {
        it('flags lines with no owner and invalid owner tokens, with 1-based line numbers', () => {
            const text = [
                '# comment',
                'products/error_tracking/** @posthog/error-tracking',
                'frontend/**',
                'docs/* not-a-handle dev@posthog.com',
            ].join('\n')

            expect(findCodeownersErrors(text)).toEqual([
                { line: 3, reason: '"frontend/**" has no owner' },
                { line: 4, reason: 'invalid owner not-a-handle' },
            ])
        })

        it('returns no errors for valid input', () => {
            expect(findCodeownersErrors('a/** @team\nb/** @user dev@posthog.com')).toEqual([])
        })
    })

    describe('splitOwner', () => {
        it.each([
            ['@posthog/frontend', { org: 'posthog', slug: 'frontend' }],
            ['posthog/error-tracking', { org: 'posthog', slug: 'error-tracking' }],
        ])('splits %s into org and slug', (owner, expected) => {
            expect(splitOwner(owner)).toEqual(expected)
        })

        it.each([['@alice'], ['dev@posthog.com'], ['@posthog/'], ['']])(
            'returns null for non-team owner %s',
            (owner) => {
                expect(splitOwner(owner)).toBeNull()
            }
        )
    })
})
