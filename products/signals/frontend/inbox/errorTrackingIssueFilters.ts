import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import {
    ISSUE_SEVERITY_OPTIONS,
    type IssueSeverity,
} from 'products/error_tracking/frontend/components/IssueSeverityTag'

// pinned: lifecycle property names the server filter reads, so renaming one breaks saved filters.
const SEVERITY_KEY = 'severity'
const ASSIGNEE_KEY = 'assignee'
// The "Issues" fields of the Issues screen that the lifecycle event carries under the same key.
const ISSUE_FIELD_KEYS = new Set(['name', 'issue_description', SEVERITY_KEY])

export interface IssueFilterDraft {
    severity: IssueSeverity | null
    assignee: ErrorTrackingIssueAssignee | null
    /** The two-level group the error tracking filter group edits: an AND root around one inner group. */
    filterGroup: UniversalFiltersGroup
}

export type IssueFilterPayload = { properties: EventPropertyFilter[] } | { error: string }

function storedProperties(value: unknown): AnyPropertyFilter[] {
    const properties = (value as { properties?: unknown } | null | undefined)?.properties
    return Array.isArray(properties)
        ? properties.filter((leaf): leaf is AnyPropertyFilter => !!leaf && typeof leaf === 'object' && 'key' in leaf)
        : []
}

/** How many conditions a stored filter holds. Zero means every issue reaches the inbox. */
export function issueFilterCount(value: unknown): number {
    return storedProperties(value).length
}

function singleExactValue(leaf: AnyPropertyFilter): string | null {
    if (
        leaf.type !== PropertyFilterType.Event ||
        (leaf.operator ?? PropertyOperator.Exact) !== PropertyOperator.Exact
    ) {
        return null
    }
    const value = Array.isArray(leaf.value) ? leaf.value : [leaf.value]
    return value.length === 1 && typeof value[0] === 'string' ? value[0] : null
}

function parseSeverity(leaf: AnyPropertyFilter): IssueSeverity | null {
    const value = leaf.key === SEVERITY_KEY ? singleExactValue(leaf) : null
    return ISSUE_SEVERITY_OPTIONS.find((option) => option.value === value)?.value ?? null
}

function parseAssignee(leaf: AnyPropertyFilter): ErrorTrackingIssueAssignee | null {
    const value = leaf.key === ASSIGNEE_KEY ? singleExactValue(leaf) : null
    if (value === null) {
        return null
    }
    try {
        const parsed = JSON.parse(value)
        return (parsed?.type === 'user' || parsed?.type === 'role') &&
            (typeof parsed.id === 'number' || typeof parsed.id === 'string')
            ? { type: parsed.type, id: parsed.id }
            : null
    } catch {
        return null
    }
}

// Same compact JSON the lifecycle events carry, `{"type":"user","id":1}`, so an exact match holds.
function assigneeValue(assignee: ErrorTrackingIssueAssignee): string {
    return JSON.stringify({ type: assignee.type, id: assignee.id })
}

/** The editable form of a stored filter. Severity and assignee get their own controls. */
export function issueFilterDraftFromStored(value: unknown): IssueFilterDraft {
    let severity: IssueSeverity | null = null
    let assignee: ErrorTrackingIssueAssignee | null = null
    const rest: AnyPropertyFilter[] = []
    for (const leaf of storedProperties(value)) {
        const parsedSeverity: IssueSeverity | null = severity === null ? parseSeverity(leaf) : null
        const parsedAssignee: ErrorTrackingIssueAssignee | null = assignee === null ? parseAssignee(leaf) : null
        if (parsedSeverity !== null) {
            severity = parsedSeverity
        } else if (parsedAssignee !== null) {
            assignee = parsedAssignee
        } else if (leaf.type === PropertyFilterType.Event && ISSUE_FIELD_KEYS.has(leaf.key)) {
            // Shown under "Issues" again, as the Issues screen labels it.
            rest.push({ ...leaf, type: PropertyFilterType.ErrorTrackingIssue } as AnyPropertyFilter)
        } else {
            rest.push(leaf)
        }
    }
    return {
        severity,
        assignee,
        filterGroup: {
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: rest }],
        },
    }
}

function hasValue(leaf: AnyPropertyFilter): boolean {
    const operator = 'operator' in leaf ? leaf.operator : undefined
    if (operator === PropertyOperator.IsSet || operator === PropertyOperator.IsNotSet) {
        return true
    }
    const value = leaf.value
    return value !== undefined && value !== null && !(Array.isArray(value) && value.length === 0)
}

/** The leaf as the event filter the server reads, or why it cannot be saved. Issue fields travel under the same key. */
function savedLeaf(leaf: AnyPropertyFilter): EventPropertyFilter | string {
    if (leaf.type === PropertyFilterType.ErrorTrackingIssue && !ISSUE_FIELD_KEYS.has(leaf.key)) {
        return leaf.key === ASSIGNEE_KEY
            ? 'Use the assignee control to filter by assignee.'
            : 'Inbox filters do not support this issue field. Remove it.'
    }
    if (leaf.type !== PropertyFilterType.Event && leaf.type !== PropertyFilterType.ErrorTrackingIssue) {
        return 'Inbox filters support exception, event, and issue properties only. Remove the others.'
    }
    if (!hasValue(leaf)) {
        return `Pick a value for ${leaf.key}, or remove that filter.`
    }
    return {
        key: leaf.key,
        type: PropertyFilterType.Event,
        operator: leaf.operator || PropertyOperator.Exact,
        ...(leaf.value !== undefined ? { value: leaf.value } : {}),
    }
}

function exactEventFilter(key: string, value: string): EventPropertyFilter {
    return { key, type: PropertyFilterType.Event, operator: PropertyOperator.Exact, value: [value] }
}

/** The filter to save, or why it cannot be saved. The server compiles the bytecode. */
export function issueFilterPayloadFromDraft(draft: IssueFilterDraft): IssueFilterPayload {
    const inner = draft.filterGroup.values[0]
    const group: UniversalFiltersGroup = isUniversalGroupFilterLike(inner)
        ? inner
        : { type: FilterLogicalOperator.And, values: [] }
    if (group.type === FilterLogicalOperator.Or && group.values.length > 1) {
        return { error: 'Inbox filters must all match. Switch "Any" to "All".' }
    }
    const properties: EventPropertyFilter[] = []
    for (const value of group.values) {
        if (isUniversalGroupFilterLike(value)) {
            return { error: 'Inbox filters do not support nested groups. Remove the group.' }
        }
        const leaf = value as AnyPropertyFilter
        const saved = savedLeaf(leaf)
        if (typeof saved === 'string') {
            return { error: saved }
        }
        properties.push(saved)
    }
    if (draft.severity) {
        properties.push(exactEventFilter(SEVERITY_KEY, draft.severity))
    }
    if (draft.assignee) {
        properties.push(exactEventFilter(ASSIGNEE_KEY, assigneeValue(draft.assignee)))
    }
    return { properties }
}

/** Adds a quick filter pick as a plain property filter, replacing an earlier pick on the same property. */
export function withQuickFilterPick(
    filterGroup: UniversalFiltersGroup,
    propertyName: string,
    pick: { operator: PropertyOperator; value: string | string[] | null } | null
): UniversalFiltersGroup {
    const inner = filterGroup.values[0]
    const group: UniversalFiltersGroup = isUniversalGroupFilterLike(inner)
        ? inner
        : { type: FilterLogicalOperator.And, values: [] }
    const kept = group.values.filter(
        (value) =>
            isUniversalGroupFilterLike(value) ||
            (value as AnyPropertyFilter).type !== PropertyFilterType.Event ||
            (value as AnyPropertyFilter).key !== propertyName
    )
    const added: EventPropertyFilter[] = pick
        ? [
              {
                  key: propertyName,
                  type: PropertyFilterType.Event,
                  operator: pick.operator,
                  ...(pick.value !== null ? { value: pick.value } : {}),
              },
          ]
        : []
    return { type: FilterLogicalOperator.And, values: [{ ...group, values: [...kept, ...added] }] }
}
