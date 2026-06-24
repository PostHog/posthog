import type { OrganizationMemberType, RoleType } from '~/types'

import {
    bestAssigneeMatch,
    entriesByOwner,
    findCodeownersErrors,
    longestCommonSubstringLength,
    ownerMatchFragments,
    patternToSourceMatch,
    parseCodeowners,
    patternToSourceValue,
} from './codeowners'

function makeRole(name: string): RoleType {
    return { id: name.toLowerCase(), name } as RoleType
}

function makeMember(firstName: string, email: string, id: number = 1): OrganizationMemberType {
    return { user: { id, first_name: firstName, email } } as OrganizationMemberType
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

    describe('entriesByOwner', () => {
        it('preserves owner entries in source order', () => {
            const entries = parseCodeowners(['a/** @team-x', 'b/** @team-y @team-x', 'a/** @team-x'].join('\n'))

            expect(entriesByOwner(entries)).toEqual([
                { owner: '@team-x', patterns: ['a/**'], index: 0 },
                { owner: '@team-y', patterns: ['b/**'], index: 1 },
                { owner: '@team-x', patterns: ['b/**'], index: 2 },
                { owner: '@team-x', patterns: ['a/**'], index: 3 },
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

    describe('longestCommonSubstringLength', () => {
        it.each([
            ['', '', 0],
            ['abc', '', 0],
            ['', 'abc', 0],
            ['error tracking', 'error tracking', 14],
            ['error tracking', 'product analytics', 2],
        ])('longest common substring length for %s and %s is %i', (a, b, expected) => {
            expect(longestCommonSubstringLength(a, b)).toBe(expected)
        })
    })

    describe('bestAssigneeMatch', () => {
        const roles = [makeRole('Frontend'), makeRole('Backend Team'), makeRole('Error Tracking')]
        const members = [
            makeMember('Alice Example', 'alice@example.com'),
            makeMember('Max Backend', 'max@example.com', 2),
        ]

        it('matches roles by longest common substring', () => {
            expect(bestAssigneeMatch('@posthog/error-tracking', roles, members)).toMatchObject({
                type: 'role',
                role: { name: 'Error Tracking' },
            })
        })

        it('matches users by name or email local part', () => {
            expect(bestAssigneeMatch('@alice', roles, members)).toMatchObject({
                type: 'user',
                user: { email: 'alice@example.com' },
            })
        })

        it('does not fuzzy match short owner tokens', () => {
            expect(bestAssigneeMatch('@dev', [makeRole('Developer experience')], [])).toBeNull()
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

        it('skips section headers', () => {
            expect(findCodeownersErrors('[Backend]\na/** @team')).toEqual([])
            expect(parseCodeowners('[Backend]\na/** @team')).toEqual([{ pattern: 'a/**', owners: ['@team'] }])
        })
    })
})
