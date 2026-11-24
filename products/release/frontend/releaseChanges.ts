export type ChangeKind = 'flag' | 'experiment' | 'survey'

export interface ActivityChange {
    readonly field: string
    readonly action?: string
    readonly before: unknown
    readonly after: unknown
}

export interface ActivityEntry {
    readonly id: string
    readonly activity: string
    readonly created_at: string
    readonly is_system?: boolean
    readonly user: { readonly [key: string]: unknown } | null
    readonly detail?: { readonly changes?: readonly ActivityChange[] }
}

export interface ReleaseChange {
    key: string
    date: string
    who: string
    lines: string[]
}

interface ConditionProperty {
    key?: string
    type?: string
    value?: unknown
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

const IGNORED_FIELDS = new Set([
    'version',
    'updated_at',
    'last_modified_at',
    'last_modified_by',
    'is_simple_flag',
    'rollout_percentage',
    'performed_rollback',
    'can_edit',
    'usage_dashboard',
    'analytics_dashboards',
])

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

function fieldLabel(field: string): string {
    return field.replace(/_/g, ' ')
}

type DescribeField = (before: unknown, after: unknown) => string[]

const SCHEDULED_FIELDS: Record<string, DescribeField> = {
    start_date: (before) => [before ? 'Changed the start date' : 'Launched'],
    archived: (_, after) => [after ? 'Archived' : 'Unarchived'],
    name: (_, after) => [`Renamed to ${String(after)}`],
}

const FIELDS: Record<ChangeKind, Map<string, DescribeField>> = {
    flag: new Map<string, DescribeField>([
        ['filters', describeFilters],
        ['active', (_, after) => [after ? 'Turned on' : 'Turned off']],
        ['key', (_, after) => [`Changed the key to ${String(after)}`]],
        ['name', () => ['Edited the description']],
        ['deleted', (_, after) => [after ? 'Deleted the flag' : 'Restored the flag']],
    ]),
    experiment: new Map<string, DescribeField>([
        ...Object.entries(SCHEDULED_FIELDS),
        ['end_date', (_, after) => [after ? 'Ended' : 'Resumed']],
        ['status', (_, after) => [`Status changed to ${String(after).toLowerCase()}`]],
        ['metrics', () => ['Edited the metrics']],
        ['metrics_secondary', () => ['Edited the metrics']],
        ['parameters', () => ['Edited the variants']],
    ]),
    survey: new Map<string, DescribeField>([
        ...Object.entries(SCHEDULED_FIELDS),
        ['end_date', (_, after) => [after ? 'Stopped' : 'Resumed']],
        ['questions', () => ['Edited the questions']],
        ['conditions', () => ['Changed who sees it']],
        ['targeting_flag_filters', () => ['Changed who sees it']],
        ['linked_flag', () => ['Changed who sees it']],
        ['appearance', () => ['Changed how it looks']],
    ]),
}

function describeField(kind: ChangeKind, change: ActivityChange): string[] {
    const { field, before, after } = change
    if (IGNORED_FIELDS.has(field)) {
        return []
    }
    const describe = FIELDS[kind].get(field)
    return describe ? describe(before, after) : [`Edited the ${fieldLabel(field)}`]
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

export function describeChange(kind: ChangeKind, entry: ActivityEntry): ReleaseChange | null {
    let lines: string[]
    if (entry.activity === 'created') {
        lines = [`Created the ${NOUN[kind]}`]
    } else if (entry.activity === 'deleted') {
        lines = [`Deleted the ${NOUN[kind]}`]
    } else if (entry.activity === 'restored') {
        lines = [`Restored the ${NOUN[kind]}`]
    } else {
        lines = [...new Set((entry.detail?.changes ?? []).flatMap((change) => describeField(kind, change)))]
    }
    if (!lines.length) {
        return null
    }
    const shown =
        lines.length > MAX_LINES
            ? [...lines.slice(0, MAX_LINES - 1), `${lines.length - MAX_LINES + 1} more changes`]
            : lines
    return { key: entry.id, date: entry.created_at, who: changeAuthor(entry), lines: shown }
}

export function describeChanges(kind: ChangeKind, entries: readonly ActivityEntry[]): ReleaseChange[] {
    return entries.flatMap((entry) => {
        const change = describeChange(kind, entry)
        return change ? [change] : []
    })
}
