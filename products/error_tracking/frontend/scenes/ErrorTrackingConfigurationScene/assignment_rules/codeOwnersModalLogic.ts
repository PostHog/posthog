import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import { ErrorTrackingIssueAssignee, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    OrganizationMemberType,
    RoleType,
    UniversalFiltersGroup,
} from '~/types'

import { assigneeSelectLogic } from '../../../components/Assignee/assigneeSelectLogic'
import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingAssignmentRule, ErrorTrackingRuleType } from '../rules/types'
import {
    CodeownersError,
    OwnerGroup,
    bestAssigneeMatch,
    findCodeownersErrors,
    groupByOwner,
    ownerMatchFragments,
    parseCodeowners,
    patternToSourceMatch,
} from './codeowners'
import type { codeOwnersModalLogicType } from './codeOwnersModalLogicType'

export type MatchSource = 'matched' | 'manual' | null

export interface CodeOwnerRow {
    owner: string
    patterns: string[]
    matchFragments: string[]
    assignee: ErrorTrackingIssueAssignee | null
    /** How `assignee` was resolved: an automatic name match, a manual pick, or unmatched. */
    source: MatchSource
    /** Normalized similarity of the fuzzy match, when `source === 'matched'`. */
    suggestionScore: number | null
}

export type MatchCount = { exceptionCount: number; issueCount: number }

/** OR-group of `$exception_sources` filters, one per (de-duped, non-empty) owned path. */
export function buildOwnerFilters(patterns: string[]): UniversalFiltersGroup {
    const matches = patterns.map(patternToSourceMatch).filter((match) => match !== null)
    const values: AnyPropertyFilter[] = Array.from(
        new Map(matches.map((match) => [`${match.operator}:${match.value}`, match])).values()
    ).map((match) => ({
        key: '$exception_sources',
        type: PropertyFilterType.Event,
        operator: match.operator === 'regex' ? PropertyOperator.Regex : PropertyOperator.IContains,
        value: match.value,
    }))
    return { type: FilterLogicalOperator.Or, values }
}

export const codeOwnersModalLogic = kea<codeOwnersModalLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'assignment_rules',
        'codeOwnersModalLogic',
    ]),

    connect(() => ({
        values: [
            rolesLogic,
            ['roles'],
            assigneeSelectLogic,
            ['meFirstMembers'],
            organizationLogic,
            ['currentOrganization'],
        ],
        actions: [rolesLogic, ['loadRoles'], assigneeSelectLogic, ['ensureAssigneeTypesLoaded']],
    })),

    actions({
        openModal: true,
        closeModal: true,
        setRawText: (rawText: string) => ({ rawText }),
        parseText: true,
        setParsedOwners: (owners: OwnerGroup[]) => ({ owners }),
        setOwnerAssignee: (owner: string, assignee: ErrorTrackingIssueAssignee | null) => ({ owner, assignee }),
        setMappingOwners: (owners: string[]) => ({ owners }),
        goToConfigure: true,
        goToImpact: true,
        backToMapping: true,
        backToPaste: true,
        setDateRange: (dateRange: string) => ({ dateRange }),
    }),

    reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        step: [
            'paste' as 'paste' | 'configure' | 'impact',
            {
                openModal: () => 'paste',
                goToConfigure: () => 'configure',
                goToImpact: () => 'impact',
                backToMapping: () => 'configure',
                backToPaste: () => 'paste',
            },
        ],
        rawText: ['', { setRawText: (_, { rawText }) => rawText, openModal: () => '' }],
        parsedOwners: [[] as OwnerGroup[], { setParsedOwners: (_, { owners }) => owners, openModal: () => [] }],
        // Manual assignee picks keyed by owner; presence of the key overrides the auto-match (null = cleared).
        assigneeOverrides: [
            {} as Record<string, ErrorTrackingIssueAssignee | null>,
            {
                setOwnerAssignee: (state, { owner, assignee }) => ({ ...state, [owner]: assignee }),
                openModal: () => ({}),
            },
        ],
        mappingOwners: [
            [] as string[],
            {
                setMappingOwners: (_, { owners }) => owners,
                openModal: () => [],
                backToPaste: () => [],
            },
        ],
        dateRange: ['-7d' as string, { setDateRange: (_, { dateRange }) => dateRange, openModal: () => '-7d' }],
    }),

    loaders(({ values }) => ({
        matchResults: [
            {} as Record<string, MatchCount | null>,
            {
                resetMatchResults: () => ({}),
                testMatches: async () => {
                    const results: Record<string, MatchCount | null> = {}
                    await Promise.all(
                        values.savableRows.map(async (row) => {
                            const filters = buildOwnerFilters(row.patterns)
                            const properties = filters.values as AnyPropertyFilter[]
                            if (properties.length === 0) {
                                results[row.owner] = null
                                return
                            }
                            const response = (await api.query({
                                kind: NodeKind.EventsQuery,
                                event: '$exception',
                                select: ['count()', 'count(distinct properties.$exception_issue_id)'],
                                after: values.dateRange,
                                fixedProperties: [{ type: filters.type, values: properties }],
                                tags: { productKey: ProductKey.ERROR_TRACKING },
                            } as Record<string, any>)) as Record<string, any>
                            results[row.owner] = {
                                exceptionCount: response.results?.[0]?.[0] ?? 0,
                                issueCount: response.results?.[0]?.[1] ?? 0,
                            }
                        })
                    )
                    return results
                },
            },
        ],
        saving: [
            false,
            {
                saveAll: async () => {
                    const rows = values.savableRows
                    await Promise.all(
                        rows.map((row, index) => {
                            const rule: ErrorTrackingAssignmentRule = {
                                id: 'new',
                                filters: buildOwnerFilters(row.patterns),
                                assignee: row.assignee,
                                disabled_data: null,
                                // Later code owner entries win: rules are first-match by ascending order_key,
                                // so the last owner gets the lowest key.
                                order_key: rows.length - 1 - index,
                            }
                            return api.errorTracking.createRule(ErrorTrackingRuleType.Assignment, rule)
                        })
                    )
                    return true
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        openModal: () => {
            actions.loadRoles()
            actions.ensureAssigneeTypesLoaded()
            actions.resetMatchResults()
        },
        setRawText: () => {
            actions.parseText()
        },
        parseText: () => {
            actions.setParsedOwners(groupByOwner(parseCodeowners(values.rawText)))
        },
        goToConfigure: () => {
            actions.setMappingOwners(values.ownerRows.map((row) => row.owner))
            actions.testMatches()
        },
        setDateRange: () => {
            if (values.step === 'impact') {
                actions.testMatches()
            }
        },
        goToImpact: () => {
            actions.testMatches()
        },
        saveAllSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Assignment }).actions.loadRules()
        },
        saveAllFailure: () => {
            lemonToast.error('Failed to save assignment rules')
        },
    })),

    selectors({
        ownerRows: [
            (s) => [s.parsedOwners, s.roles, s.meFirstMembers, s.assigneeOverrides],
            (
                parsedOwners: OwnerGroup[],
                roles: RoleType[],
                meFirstMembers: OrganizationMemberType[],
                assigneeOverrides: Record<string, ErrorTrackingIssueAssignee | null>
            ): CodeOwnerRow[] =>
                parsedOwners.map(({ owner, patterns }) => {
                    const base = { owner, patterns, matchFragments: ownerMatchFragments(patterns) }

                    if (Object.prototype.hasOwnProperty.call(assigneeOverrides, owner)) {
                        const assignee = assigneeOverrides[owner]
                        return { ...base, assignee, source: assignee ? 'manual' : null, suggestionScore: null }
                    }

                    const match = bestAssigneeMatch(owner, roles, meFirstMembers)
                    return {
                        ...base,
                        assignee: match
                            ? match.type === 'role'
                                ? { type: 'role', id: match.role.id }
                                : { type: 'user', id: match.user.id }
                            : null,
                        source: match ? 'matched' : null,
                        suggestionScore: match?.score ?? null,
                    }
                }),
        ],
        savableRows: [
            (s) => [s.ownerRows],
            (rows: CodeOwnerRow[]): CodeOwnerRow[] => {
                const groupedRows = new Map<string, CodeOwnerRow>()

                for (const row of rows) {
                    if (row.assignee === null || buildOwnerFilters(row.patterns).values.length === 0) {
                        continue
                    }

                    const key = `${row.assignee.type}:${row.assignee.id}`
                    const existing = groupedRows.get(key)
                    if (existing) {
                        existing.owner = `${existing.owner}, ${row.owner}`
                        existing.patterns.push(...row.patterns)
                    } else {
                        groupedRows.set(key, { ...row, patterns: [...row.patterns] })
                    }
                }

                return Array.from(groupedRows.values())
            },
        ],
        mappingRows: [
            (s) => [s.ownerRows, s.mappingOwners],
            (rows: CodeOwnerRow[], mappingOwners: string[]): CodeOwnerRow[] =>
                rows.filter((row) => mappingOwners.includes(row.owner)),
        ],
        hasParsedOwners: [(s) => [s.parsedOwners], (owners: OwnerGroup[]): boolean => owners.length > 0],
        parseErrors: [(s) => [s.rawText], (rawText: string): CodeownersError[] => findCodeownersErrors(rawText)],
        unmatchedCount: [
            (s) => [s.ownerRows],
            (rows: CodeOwnerRow[]): number => rows.filter((r) => r.assignee === null).length,
        ],
        mappingUnresolvedCount: [
            (s) => [s.mappingRows],
            (rows: CodeOwnerRow[]): number => rows.filter((r) => r.assignee === null).length,
        ],
    }),
])
