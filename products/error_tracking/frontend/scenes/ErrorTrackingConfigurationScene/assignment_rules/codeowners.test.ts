import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    OrganizationMemberType,
    PropertyFilterType,
    PropertyOperator,
    RoleType,
} from '~/types'

import { matchingExceptionsUrl, matchingIssuesUrl } from '../rules/ruleMatchUrls'
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
import { buildImpactRows } from './codeownersImpact'
import { CodeOwnerRuleCandidate, buildMappingRows, buildOwnerFilters, buildSavableRows } from './codeownersImport'
import { exceptionsUrl as codeOwnersExceptionsUrl, issuesUrl as codeOwnersIssuesUrl } from './codeownersUrls'

function makeRole(name: string): RoleType {
    return { id: name.toLowerCase(), name } as RoleType
}

function makeMember(firstName: string, email: string, id: number = 1): OrganizationMemberType {
    return { user: { id, first_name: firstName, email } } as OrganizationMemberType
}

function candidate(
    owner: string,
    assignee: ErrorTrackingIssueAssignee | null,
    patterns: string[],
    orderIndex: number
): CodeOwnerRuleCandidate {
    return {
        entryId: `${orderIndex}:${owner}`,
        orderIndex,
        owner,
        patterns,
        matchFragments: ownerMatchFragments(patterns),
        assignee,
    }
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

    describe('buildSavableRows', () => {
        it('merges candidates by assignee and keeps source order precedence', () => {
            const assignee = { type: 'role' as const, id: 'error-tracking' }
            const rows = [
                candidate('@team/error-tracking', assignee, ['a/**'], 0),
                candidate('@team/error-tracking-oncall', assignee, ['b/**'], 2),
                candidate('@unmapped', null, ['c/**'], 3),
                candidate('@empty', { type: 'user' as const, id: 1 }, ['*'], 4),
            ]

            expect(buildSavableRows(rows)).toMatchObject([
                {
                    owner: '@team/error-tracking, @team/error-tracking-oncall',
                    orderIndex: 2,
                    patterns: ['a/**', 'b/**'],
                    assignee,
                },
            ])
        })
    })

    describe('buildMappingRows', () => {
        it('dedupes owners while keeping all patterns', () => {
            const rows = [
                candidate('@team/error-tracking', null, ['a/**'], 0),
                candidate('@team/frontend', null, ['b/**'], 1),
                candidate('@team/error-tracking', null, ['c/**'], 2),
            ]

            expect(buildMappingRows(rows, ['@team/error-tracking'])).toMatchObject([
                { owner: '@team/error-tracking', patterns: ['a/**', 'c/**'] },
            ])
        })
    })

    describe('buildImpactRows', () => {
        it('groups counts by resolved assignee', () => {
            const assignee = { type: 'role' as const, id: 'error-tracking' }
            const rows = [
                candidate('@team/error-tracking', assignee, ['a/**'], 0),
                candidate('@oncall', assignee, ['b/**'], 1),
            ]
            const role = makeRole('Error tracking')

            expect(
                buildImpactRows(
                    rows,
                    {
                        '0:@team/error-tracking': { exceptionCount: 2, issueCount: 1 },
                        '1:@oncall': { exceptionCount: 3, issueCount: 2 },
                    },
                    () => ({ id: role.id, type: 'role', role })
                )
            ).toEqual([
                {
                    key: 'role:error-tracking',
                    label: 'Error tracking',
                    exceptionCount: 5,
                    issueCount: 3,
                    patterns: ['a/**', 'b/**'],
                },
            ])
        })
    })

    describe('rule match URLs', () => {
        const browserFilter: AnyPropertyFilter = {
            key: '$browser',
            value: ['Firefox'],
            type: PropertyFilterType.Event,
            operator: PropertyOperator.Exact,
        }

        it('builds exception and issue links for normal rule filters', () => {
            const exceptionsUrl = decodeURIComponent(matchingExceptionsUrl([browserFilter], '-30d'))
            const issuesUrl = decodeURIComponent(matchingIssuesUrl([browserFilter], FilterLogicalOperator.And, '-30d'))

            expect(exceptionsUrl).toContain('$exception')
            expect(exceptionsUrl).toContain('timestamp DESC')
            expect(exceptionsUrl).toContain('-30d')
            expect(issuesUrl).toContain('filterGroup')
            expect(issuesUrl).toContain('"date_from":"-30d"')
        })

        it('uses the same rule match URL helpers for code owners impact links', () => {
            const patterns = ['products/error_tracking/**']
            const filters = buildOwnerFilters(patterns)

            expect(codeOwnersExceptionsUrl(patterns, '-90d')).toEqual(
                matchingExceptionsUrl(filters.values as AnyPropertyFilter[], '-90d')
            )
            expect(codeOwnersIssuesUrl(patterns, '-90d')).toEqual(
                matchingIssuesUrl(filters.values as AnyPropertyFilter[], filters.type, '-90d')
            )
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
                { line: 3, reason: 'Missing owner' },
                { line: 4, reason: 'Invalid owner' },
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
