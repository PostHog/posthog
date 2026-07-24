import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    OrganizationMemberType,
    PropertyFilterType,
    PropertyOperator,
    RoleType,
    UniversalFiltersGroup,
} from '~/types'

import { bestAssigneeMatch, OwnerGroup, ownerMatchFragments, patternToSourceMatch } from './codeowners'

export interface CodeOwnerRuleCandidate {
    entryId: string
    orderIndex: number
    owner: string
    patterns: string[]
    matchFragments: string[]
    assignee: ErrorTrackingIssueAssignee | null
}

export interface CodeOwnerOwnerMapping {
    owner: string
    patterns: string[]
    matchFragments: string[]
    assignee: ErrorTrackingIssueAssignee | null
}

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

export function buildOwnerRows(
    parsedOwners: OwnerGroup[],
    roles: RoleType[],
    meFirstMembers: OrganizationMemberType[],
    assigneeOverrides: Record<string, ErrorTrackingIssueAssignee | null>
): CodeOwnerRuleCandidate[] {
    return parsedOwners.map(({ owner, patterns, index }) => {
        const base = {
            entryId: `${index}:${owner}`,
            orderIndex: index,
            owner,
            patterns,
            matchFragments: ownerMatchFragments(patterns),
        }

        if (Object.prototype.hasOwnProperty.call(assigneeOverrides, owner)) {
            return { ...base, assignee: assigneeOverrides[owner] }
        }

        const match = bestAssigneeMatch(owner, roles, meFirstMembers)
        const assignee = match
            ? match.type === 'role'
                ? { type: 'role' as const, id: match.role.id }
                : { type: 'user' as const, id: match.user.id }
            : null
        return { ...base, assignee }
    })
}

export function buildSavableRows(rows: CodeOwnerRuleCandidate[]): CodeOwnerRuleCandidate[] {
    const rowsByAssignee = new Map<string, CodeOwnerRuleCandidate>()

    for (const row of rows) {
        if (row.assignee === null || buildOwnerFilters(row.patterns).values.length === 0) {
            continue
        }

        const key = `${row.assignee.type}:${row.assignee.id}`
        const existing = rowsByAssignee.get(key)
        if (!existing) {
            rowsByAssignee.set(key, { ...row, patterns: [...row.patterns], matchFragments: [...row.matchFragments] })
            continue
        }

        if (row.orderIndex > existing.orderIndex) {
            existing.orderIndex = row.orderIndex
            existing.entryId = row.entryId
        }
        existing.owner = existing.owner.includes(row.owner) ? existing.owner : `${existing.owner}, ${row.owner}`
        existing.patterns.push(...row.patterns)
        existing.matchFragments = ownerMatchFragments(existing.patterns)
    }

    return Array.from(rowsByAssignee.values()).sort((a, b) => a.orderIndex - b.orderIndex)
}

export function buildMappingRows(rows: CodeOwnerRuleCandidate[], mappingOwners: string[]): CodeOwnerOwnerMapping[] {
    const mappingOwnerSet = new Set(mappingOwners)
    const rowsByOwner = new Map<string, CodeOwnerOwnerMapping>()

    for (const row of rows) {
        if (!mappingOwnerSet.has(row.owner)) {
            continue
        }

        const existing = rowsByOwner.get(row.owner)
        if (existing) {
            existing.patterns.push(...row.patterns)
            existing.matchFragments = ownerMatchFragments(existing.patterns)
            continue
        }

        rowsByOwner.set(row.owner, {
            owner: row.owner,
            patterns: [...row.patterns],
            matchFragments: [...row.matchFragments],
            assignee: row.assignee,
        })
    }

    return Array.from(rowsByOwner.values())
}
