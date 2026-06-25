import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import { ErrorTrackingIssueAssignee, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, OrganizationMemberType, RoleType } from '~/types'

import { assigneeSelectLogic } from '../../../components/Assignee/assigneeSelectLogic'
import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingAssignmentRule, ErrorTrackingRuleType } from '../rules/types'
import { CodeownersError, OwnerGroup, entriesByOwner, findCodeownersErrors, parseCodeowners } from './codeowners'
import {
    CodeOwnerOwnerMapping,
    CodeOwnerRuleCandidate,
    buildMappingRows,
    buildOwnerFilters,
    buildOwnerRows,
    buildSavableRows,
} from './codeownersImport'
import type { codeOwnersModalLogicType } from './codeOwnersModalLogicType'

export type MatchCount = { exceptionCount: number; issueCount: number }
export type SaveAllResult = { createdCount: number; failedCount: number; totalCount: number }
export type CodeOwnerEntryRow = CodeOwnerRuleCandidate
export type CodeOwnerMappingRow = CodeOwnerOwnerMapping

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
        setOwnerAssignee: (owner: string, assignee: ErrorTrackingIssueAssignee | null) => ({ owner, assignee }),
        setOwnersToMap: (owners: string[]) => ({ owners }),
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
        // Manual assignee picks keyed by owner; presence of the key overrides the auto-match (null = cleared).
        assigneeOverrides: [
            {} as Record<string, ErrorTrackingIssueAssignee | null>,
            {
                setOwnerAssignee: (state, { owner, assignee }) => ({ ...state, [owner]: assignee }),
                openModal: () => ({}),
            },
        ],
        ownersToMap: [
            [] as string[],
            {
                setOwnersToMap: (_, { owners }) => owners,
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
                                results[row.entryId] = null
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
                            results[row.entryId] = {
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
            { createdCount: 0, failedCount: 0, totalCount: 0 } as SaveAllResult,
            {
                saveAll: async (): Promise<SaveAllResult> => {
                    const rows = values.savableRows
                    const results = await Promise.allSettled(
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
                    const failedCount = results.filter((result) => result.status === 'rejected').length
                    const createdCount = results.length - failedCount
                    if (createdCount === 0 && failedCount > 0) {
                        throw new Error('Failed to save assignment rules')
                    }
                    return { createdCount, failedCount, totalCount: rows.length }
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
        goToConfigure: () => {
            actions.setOwnersToMap(values.ownerRows.map((row) => row.owner))
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
        saveAllSuccess: ({ saving }) => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Assignment }).actions.loadRules()
            if (saving.failedCount > 0) {
                lemonToast.warning(
                    `Created ${saving.createdCount} of ${saving.totalCount} assignment rules. ${saving.failedCount} failed.`
                )
            }
        },
        saveAllFailure: () => {
            rulesLogic({ ruleType: ErrorTrackingRuleType.Assignment }).actions.loadRules()
            lemonToast.error('Failed to save assignment rules')
        },
    })),

    selectors({
        parsedOwners: [(s) => [s.rawText], (rawText: string): OwnerGroup[] => entriesByOwner(parseCodeowners(rawText))],
        ownerRows: [
            (s) => [s.parsedOwners, s.roles, s.meFirstMembers, s.assigneeOverrides],
            (
                parsedOwners: OwnerGroup[],
                roles: RoleType[],
                meFirstMembers: OrganizationMemberType[],
                assigneeOverrides: Record<string, ErrorTrackingIssueAssignee | null>
            ): CodeOwnerRuleCandidate[] => buildOwnerRows(parsedOwners, roles, meFirstMembers, assigneeOverrides),
        ],
        savableRows: [
            (s) => [s.ownerRows],
            (rows: CodeOwnerRuleCandidate[]): CodeOwnerRuleCandidate[] => buildSavableRows(rows),
        ],
        mappingRows: [
            (s) => [s.ownerRows, s.ownersToMap],
            (rows: CodeOwnerRuleCandidate[], ownersToMap: string[]): CodeOwnerOwnerMapping[] =>
                buildMappingRows(rows, ownersToMap),
        ],
        hasParsedOwners: [(s) => [s.parsedOwners], (owners: OwnerGroup[]): boolean => owners.length > 0],
        parseErrors: [(s) => [s.rawText], (rawText: string): CodeownersError[] => findCodeownersErrors(rawText)],
        unmatchedCount: [
            (s) => [s.ownerRows],
            (rows: CodeOwnerRuleCandidate[]): number => rows.filter((r) => r.assignee === null).length,
        ],
        mappingUnresolvedCount: [
            (s) => [s.mappingRows],
            (rows: CodeOwnerOwnerMapping[]): number => rows.filter((r) => r.assignee === null).length,
        ],
    }),
])
