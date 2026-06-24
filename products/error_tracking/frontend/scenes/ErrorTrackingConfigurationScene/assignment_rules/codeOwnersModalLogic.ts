import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import { ErrorTrackingIssueAssignee, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RoleType,
    UniversalFiltersGroup,
} from '~/types'

import { roleExternalReferencesCreate, roleExternalReferencesList } from 'products/integrations/frontend/generated/api'
import { RoleExternalReferenceApi } from 'products/integrations/frontend/generated/api.schemas'

import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingAssignmentRule, ErrorTrackingRuleType } from '../rules/types'
import {
    CodeownersError,
    OwnerGroup,
    bestRoleMatch,
    findCodeownersErrors,
    groupByOwner,
    ownerMatchFragments,
    parseCodeowners,
    splitOwner,
} from './codeowners'
import type { codeOwnersModalLogicType } from './codeOwnersModalLogicType'

// CODEOWNERS owners are GitHub teams (`@org/team`), so saved mappings live on the `github` provider —
// interoperable with any real GitHub-team → role references.
const MAPPING_PROVIDER = 'github'

/** Stable key for a persisted owner mapping: lowercased `org/slug`. */
function referenceKey(org: string, slug: string): string {
    return `${org.toLowerCase()}/${slug.toLowerCase()}`
}

export type MatchSource = 'saved' | 'matched' | 'manual' | null

export interface CodeOwnerRow {
    owner: string
    patterns: string[]
    matchFragments: string[]
    assignee: ErrorTrackingIssueAssignee | null
    /** How `assignee` was resolved: a saved mapping, a fuzzy name match, a manual pick, or unmatched. */
    source: MatchSource
    /** Normalized similarity of the fuzzy match, when `source === 'matched'`. */
    suggestionScore: number | null
}

export type MatchCount = { exceptionCount: number; issueCount: number }

/** OR-group of `$exception_sources icontains` filters, one per (de-duped, non-empty) owned path. */
export function buildOwnerFilters(patterns: string[]): UniversalFiltersGroup {
    const values: AnyPropertyFilter[] = ownerMatchFragments(patterns).map((value) => ({
        key: '$exception_sources',
        type: PropertyFilterType.Event,
        operator: PropertyOperator.IContains,
        value,
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
        values: [rolesLogic, ['roles'], organizationLogic, ['currentOrganization']],
        actions: [rolesLogic, ['loadRoles']],
    })),

    actions({
        openModal: true,
        closeModal: true,
        setRawText: (rawText: string) => ({ rawText }),
        parseText: true,
        setParsedOwners: (owners: OwnerGroup[]) => ({ owners }),
        setOwnerAssignee: (owner: string, assignee: ErrorTrackingIssueAssignee | null) => ({ owner, assignee }),
        setMappingOwners: (owners: string[]) => ({ owners }),
        setSaveMapping: (saveMapping: boolean) => ({ saveMapping }),
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
                closeModal: () => 'paste',
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
                closeModal: () => [],
            },
        ],
        saveMapping: [false, { setSaveMapping: (_, { saveMapping }) => saveMapping, openModal: () => false }],
        dateRange: ['-7d' as string, { setDateRange: (_, { dateRange }) => dateRange, openModal: () => '-7d' }],
    }),

    loaders(({ values }) => ({
        externalReferences: [
            [] as RoleExternalReferenceApi[],
            {
                loadExternalReferences: async () => {
                    const orgId = values.currentOrganization?.id
                    if (!orgId) {
                        return []
                    }
                    const response = await roleExternalReferencesList(orgId, { limit: 1000 })
                    return response.results.filter(
                        (ref) => ref.provider === MAPPING_PROVIDER && !!ref.provider_role_slug
                    )
                },
            },
        ],
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
                                // Later CODEOWNERS entries win (GitHub's last-match-wins): rules are
                                // first-match by ascending order_key, so the last owner gets the lowest key.
                                order_key: rows.length - 1 - index,
                            }
                            return api.errorTracking.createRule(ErrorTrackingRuleType.Assignment, rule)
                        })
                    )
                    // Persist owner → role mappings best-effort: rules are the primary action, so a
                    // failed mapping write (e.g. an already-existing reference) must not fail the save.
                    const orgId = values.currentOrganization?.id
                    if (values.saveMapping && orgId) {
                        await Promise.allSettled(
                            values.mappingsToPersist.map((ref) => roleExternalReferencesCreate(orgId, ref))
                        )
                    }
                    return true
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        openModal: () => {
            actions.loadRoles()
            actions.loadExternalReferences()
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
    })),

    selectors({
        // Saved owner → role id, keyed by lowercased `org/slug`, restricted to roles that still exist.
        referenceRoleByKey: [
            (s) => [s.externalReferences, s.roles],
            (externalReferences: RoleExternalReferenceApi[], roles: RoleType[]): Record<string, string> => {
                const roleIds = new Set(roles.map((role) => role.id))
                const map: Record<string, string> = {}
                for (const ref of externalReferences) {
                    if (ref.provider_role_slug && roleIds.has(ref.role)) {
                        map[referenceKey(ref.provider_organization_id, ref.provider_role_slug)] = ref.role
                    }
                }
                return map
            },
        ],
        ownerRows: [
            (s) => [s.parsedOwners, s.roles, s.referenceRoleByKey, s.assigneeOverrides],
            (
                parsedOwners: OwnerGroup[],
                roles: RoleType[],
                referenceRoleByKey: Record<string, string>,
                assigneeOverrides: Record<string, ErrorTrackingIssueAssignee | null>
            ): CodeOwnerRow[] =>
                parsedOwners.map(({ owner, patterns }) => {
                    const base = { owner, patterns, matchFragments: ownerMatchFragments(patterns) }

                    if (Object.prototype.hasOwnProperty.call(assigneeOverrides, owner)) {
                        const assignee = assigneeOverrides[owner]
                        return { ...base, assignee, source: assignee ? 'manual' : null, suggestionScore: null }
                    }

                    const identity = splitOwner(owner)
                    const savedRoleId = identity
                        ? referenceRoleByKey[referenceKey(identity.org, identity.slug)]
                        : undefined
                    if (savedRoleId) {
                        return {
                            ...base,
                            assignee: { type: 'role', id: savedRoleId },
                            source: 'saved',
                            suggestionScore: null,
                        }
                    }

                    const match = bestRoleMatch(owner, roles)
                    return {
                        ...base,
                        assignee: match ? { type: 'role', id: match.role.id } : null,
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
        // Role mappings worth persisting: role assignees with an `@org/team` owner not already saved.
        mappingsToPersist: [
            (s) => [s.ownerRows, s.referenceRoleByKey],
            (ownerRows: CodeOwnerRow[], referenceRoleByKey: Record<string, string>): RoleExternalReferenceApi[] => {
                const refs: RoleExternalReferenceApi[] = []
                for (const row of ownerRows) {
                    const identity = splitOwner(row.owner)
                    if (!identity || row.assignee?.type !== 'role') {
                        continue
                    }
                    if (referenceRoleByKey[referenceKey(identity.org, identity.slug)]) {
                        continue
                    }
                    refs.push({
                        provider: MAPPING_PROVIDER,
                        provider_organization_id: identity.org,
                        provider_role_id: '',
                        provider_role_slug: identity.slug,
                        provider_role_name: row.owner,
                        role: String(row.assignee.id),
                    } as RoleExternalReferenceApi)
                }
                return refs
            },
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
