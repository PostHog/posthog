import type { ActivityLogEntryApi, ChangeApi, DetailApi } from 'products/feature_flags/frontend/generated/api.schemas'

import type { Lane } from './releaseTracks'

export type ChangeKind = 'flag' | 'experiment' | 'survey'

export type ActivityObjectKind = 'experiment' | 'survey'

export function activityKey(kind: ActivityObjectKind, id: string | number): string {
    return `${kind}:${id}`
}

export function laneActivity(lane: Lane): { kind: ChangeKind; key: string | null } | null {
    if (lane.kind === 'flag') {
        return { kind: 'flag', key: null }
    }
    if (lane.kind === 'experiment') {
        return { kind: 'experiment', key: activityKey('experiment', lane.key.replace(/^experiment-/, '')) }
    }
    if (lane.kind === 'survey') {
        return { kind: 'survey', key: activityKey('survey', lane.survey.id) }
    }
    return null
}

export type ActivityChange = Pick<ChangeApi, 'field' | 'before' | 'after'>

export type ActivityEntry = Pick<ActivityLogEntryApi, 'id' | 'activity' | 'created_at' | 'user'> &
    Partial<Pick<ActivityLogEntryApi, 'is_system' | 'scope'>> & {
        readonly detail?: Partial<Pick<DetailApi, 'type'>> & { readonly changes?: readonly ActivityChange[] }
    }

export interface ReleaseChange {
    key: string
    date: string
    who: string
    lines: string[]
    applied: string[]
}

interface ConditionProperty {
    key?: string
    type?: string
    value?: unknown
    operator?: string
    cohort_name?: string
}

interface ConditionGroup {
    properties?: ConditionProperty[]
    rollout_percentage?: number | null
}

interface FlagFilters {
    groups?: ConditionGroup[]
    multivariate?: { variants?: { key: string; rollout_percentage: number }[] } | null
}

const NOUN: Record<ChangeKind, string> = { flag: 'flag', experiment: 'experiment', survey: 'survey' }

const OPERATOR_TEXT: Record<string, string> = {
    exact: 'is',
    is_not: 'is not',
    icontains: 'contains',
    not_icontains: 'does not contain',
    regex: 'matches',
    not_regex: 'does not match',
    gt: '>',
    gte: '≥',
    lt: '<',
    lte: '≤',
    is_set: 'is set',
    is_not_set: 'is not set',
    in: 'is in',
    not_in: 'is not in',
}

const MAX_LINES = 3

function plural(count: number, one: string, many: string): string {
    return `${count} ${count === 1 ? one : many}`
}

function cohortName(property: ConditionProperty): string {
    return property.cohort_name ? `cohort ${property.cohort_name}` : 'a cohort'
}

function cohorts(filters: FlagFilters): Map<string, ConditionProperty> {
    const found = new Map<string, ConditionProperty>()
    for (const group of filters.groups ?? []) {
        for (const property of group.properties ?? []) {
            if (property.type === 'cohort') {
                found.set(String(property.value), property)
            }
        }
    }
    return found
}

function propertyKeys(filters: FlagFilters): string[] {
    return (filters.groups ?? []).flatMap((group) =>
        (group.properties ?? [])
            .filter((property) => property.type !== 'cohort')
            .map((property) => `${property.type}:${property.key}:${JSON.stringify(property.value)}`)
    )
}

function rollout(group: ConditionGroup | undefined): number {
    return group?.rollout_percentage ?? 100
}

function describeCohorts(before: FlagFilters, after: FlagFilters): string[] {
    const beforeCohorts = cohorts(before)
    const afterCohorts = cohorts(after)
    return [
        ...[...afterCohorts]
            .filter(([id]) => !beforeCohorts.has(id))
            .map(([, property]) => `Added ${cohortName(property)}`),
        ...[...beforeCohorts]
            .filter(([id]) => !afterCohorts.has(id))
            .map(([, property]) => `Removed ${cohortName(property)}`),
    ]
}

function describeGroups(
    beforeGroups: ConditionGroup[],
    afterGroups: ConditionGroup[],
    cohortsChanged: boolean
): string[] {
    const delta = afterGroups.length - beforeGroups.length
    if (delta !== 0) {
        if (cohortsChanged) {
            return []
        }
        return [`${delta > 0 ? 'Added' : 'Removed'} ${plural(Math.abs(delta), 'condition set', 'condition sets')}`]
    }
    return afterGroups.flatMap((group, index) => {
        const from = rollout(beforeGroups[index])
        const to = rollout(group)
        if (from === to) {
            return []
        }
        return [
            afterGroups.length === 1
                ? `Rollout ${from}% to ${to}%`
                : `Condition set ${index + 1}: rollout ${from}% to ${to}%`,
        ]
    })
}

function describeConditions(before: FlagFilters, after: FlagFilters): string[] {
    const beforeProperties = propertyKeys(before)
    const afterProperties = propertyKeys(after)
    const changed =
        beforeProperties.length !== afterProperties.length ||
        beforeProperties.some((property, index) => property !== afterProperties[index])
    const sameGroupCount = (after.groups ?? []).length === (before.groups ?? []).length
    return changed && sameGroupCount ? ['Changed the conditions'] : []
}

function describeVariants(before: FlagFilters, after: FlagFilters): string[] {
    const beforeVariants = before.multivariate?.variants ?? []
    const afterVariants = after.multivariate?.variants ?? []
    const beforeSplit = new Map(beforeVariants.map((variant) => [variant.key, variant.rollout_percentage]))
    const afterKeys = new Set(afterVariants.map((variant) => variant.key))
    const lines = [
        ...afterVariants
            .filter((variant) => !beforeSplit.has(variant.key))
            .map((variant) => `Added variant ${variant.key}`),
        ...beforeVariants
            .filter((variant) => !afterKeys.has(variant.key))
            .map((variant) => `Removed variant ${variant.key}`),
    ]
    const splitChanged = afterVariants.some(
        (variant) => beforeSplit.has(variant.key) && beforeSplit.get(variant.key) !== variant.rollout_percentage
    )
    if (splitChanged) {
        lines.push(
            `Variant split ${afterVariants.map((variant) => `${variant.key} ${variant.rollout_percentage}%`).join(', ')}`
        )
    }
    return lines
}

export function describeFilters(beforeValue: unknown, afterValue: unknown): string[] {
    const before = (beforeValue ?? {}) as FlagFilters
    const after = (afterValue ?? {}) as FlagFilters
    const cohortLines = describeCohorts(before, after)
    const lines = [
        ...cohortLines,
        ...describeGroups(before.groups ?? [], after.groups ?? [], cohortLines.length > 0),
        ...describeConditions(before, after),
        ...describeVariants(before, after),
    ]
    return lines.length ? lines : ['Changed the release conditions']
}

type DescribeField = (before: unknown, after: unknown) => string[]

const SCHEDULED_FIELDS: Record<string, DescribeField> = {
    start_date: (before) => [before ? 'Changed the start date' : 'Launched'],
    archived: (_, after) => [after ? 'Archived' : 'Unarchived'],
}

const FIELDS: Record<ChangeKind, Map<string, DescribeField>> = {
    flag: new Map<string, DescribeField>([
        ['filters', describeFilters],
        ['active', (_, after) => [after ? 'Turned on' : 'Turned off']],
        ['deleted', (_, after) => [after ? 'Deleted the flag' : 'Restored the flag']],
    ]),
    experiment: new Map<string, DescribeField>([
        ...Object.entries(SCHEDULED_FIELDS),
        ['end_date', (_, after) => [after ? 'Ended' : 'Resumed']],
        ['status', (_, after) => [`Status changed to ${String(after).toLowerCase()}`]],
        ['parameters', () => ['Edited the variants']],
    ]),
    survey: new Map<string, DescribeField>([
        ...Object.entries(SCHEDULED_FIELDS),
        ['end_date', (_, after) => [after ? 'Stopped' : 'Resumed']],
        ['conditions', () => ['Changed who sees it']],
        ['targeting_flag_filters', () => ['Changed who sees it']],
        ['linked_flag', () => ['Changed who sees it']],
    ]),
}

function describeField(kind: ChangeKind, change: ActivityChange): string[] {
    return FIELDS[kind].get(change.field)?.(change.before, change.after) ?? []
}

function propertyValue(value: unknown): string {
    return Array.isArray(value) ? value.join(', ') : String(value)
}

function propertyText(property: ConditionProperty): string {
    if (property.type === 'cohort') {
        return property.operator === 'not_in' ? `not in ${cohortName(property)}` : cohortName(property)
    }
    const operator = property.operator ? (OPERATOR_TEXT[property.operator] ?? property.operator) : 'is'
    return ['is_set', 'is_not_set'].includes(property.operator ?? '')
        ? `${property.key} ${operator}`
        : `${property.key} ${operator} ${propertyValue(property.value)}`
}

function appliedConditions(kind: ChangeKind, change: ActivityChange): string[] {
    if (kind !== 'flag' || change.field !== 'filters') {
        return []
    }
    return (((change.after ?? {}) as FlagFilters).groups ?? []).map((group) => {
        const who = group.properties?.length ? group.properties.map(propertyText).join(' and ') : 'Everyone'
        return `${who} · ${rollout(group)}%`
    })
}

export function changeAuthor(entry: ActivityEntry): string {
    const firstName = entry.user?.first_name
    const email = entry.user?.email
    if (typeof firstName === 'string' && firstName) {
        return firstName
    }
    if (typeof email === 'string' && email) {
        return email
    }
    return entry.is_system || !entry.user ? 'PostHog' : 'Someone'
}

const LIFECYCLE_VERBS = new Map([
    ['created', 'Created'],
    ['deleted', 'Deleted'],
    ['restored', 'Restored'],
])

const CHILD_NOUNS = new Map([['holdout', 'holdout']])

const SKIPPED_TYPES = new Set(['shared_metric'])

interface ChangeSubject {
    kind: ChangeKind
    noun: string
    child: boolean
}

function changeSubject(kind: ChangeKind, entry: ActivityEntry): ChangeSubject {
    if (entry.scope === 'FeatureFlag') {
        return { kind: 'flag', noun: kind === 'flag' ? 'flag' : 'linked flag', child: false }
    }
    const childNoun = CHILD_NOUNS.get(entry.detail?.type ?? '')
    if (childNoun) {
        return { kind, noun: childNoun, child: true }
    }
    return { kind, noun: NOUN[kind], child: false }
}

export function describeChange(kind: ChangeKind, entry: ActivityEntry): ReleaseChange | null {
    const subject = changeSubject(kind, entry)
    if (SKIPPED_TYPES.has(entry.detail?.type ?? '') || (entry.activity === 'created' && !subject.child)) {
        return null
    }
    const verb = LIFECYCLE_VERBS.get(entry.activity) ?? (subject.child ? 'Edited' : undefined)
    const changes = entry.detail?.changes ?? []
    const lines = verb
        ? [`${verb} the ${subject.noun}`]
        : [...new Set(changes.flatMap((change) => describeField(subject.kind, change)))]
    if (!lines.length) {
        return null
    }
    const shown =
        lines.length > MAX_LINES
            ? [...lines.slice(0, MAX_LINES - 1), `${lines.length - MAX_LINES + 1} more changes`]
            : lines
    const applied = verb ? [] : changes.flatMap((change) => appliedConditions(subject.kind, change))
    return { key: entry.id, date: entry.created_at, who: changeAuthor(entry), lines: shown, applied }
}

export function describeChanges(kind: ChangeKind, entries: readonly ActivityEntry[]): ReleaseChange[] {
    return entries.flatMap((entry) => {
        const change = describeChange(kind, entry)
        return change ? [change] : []
    })
}
