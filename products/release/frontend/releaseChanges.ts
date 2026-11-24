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

export function describeFilters(beforeValue: unknown, afterValue: unknown): string[] {
    const before = (beforeValue ?? {}) as FlagFilters
    const after = (afterValue ?? {}) as FlagFilters
    const lines: string[] = []
    const beforeGroups = before.groups ?? []
    const afterGroups = after.groups ?? []

    const beforeCohorts = cohorts(before)
    const afterCohorts = cohorts(after)
    for (const [id, property] of afterCohorts) {
        if (!beforeCohorts.has(id)) {
            lines.push(`Added ${cohortName(property)}`)
        }
    }
    for (const [id, property] of beforeCohorts) {
        if (!afterCohorts.has(id)) {
            lines.push(`Removed ${cohortName(property)}`)
        }
    }

    if (afterGroups.length > beforeGroups.length) {
        lines.push(`Added ${plural(afterGroups.length - beforeGroups.length, 'condition set', 'condition sets')}`)
    } else if (afterGroups.length < beforeGroups.length) {
        lines.push(`Removed ${plural(beforeGroups.length - afterGroups.length, 'condition set', 'condition sets')}`)
    } else {
        afterGroups.forEach((group, index) => {
            const from = rollout(beforeGroups[index])
            const to = rollout(group)
            if (from !== to) {
                lines.push(
                    afterGroups.length === 1
                        ? `Rollout ${from}% to ${to}%`
                        : `Condition set ${index + 1}: rollout ${from}% to ${to}%`
                )
            }
        })
    }

    const beforeProperties = propertyKeys(before)
    const afterProperties = propertyKeys(after)
    const propertiesChanged =
        beforeProperties.length !== afterProperties.length ||
        beforeProperties.some((property, index) => property !== afterProperties[index])
    if (propertiesChanged && afterGroups.length === beforeGroups.length) {
        lines.push('Changed the conditions')
    }

    const beforeVariants = before.multivariate?.variants ?? []
    const afterVariants = after.multivariate?.variants ?? []
    const beforeKeys = new Set(beforeVariants.map((variant) => variant.key))
    const afterKeys = new Set(afterVariants.map((variant) => variant.key))
    for (const variant of afterVariants) {
        if (!beforeKeys.has(variant.key)) {
            lines.push(`Added variant ${variant.key}`)
        }
    }
    for (const variant of beforeVariants) {
        if (!afterKeys.has(variant.key)) {
            lines.push(`Removed variant ${variant.key}`)
        }
    }
    const splitChanged = afterVariants.some(
        (variant) =>
            beforeKeys.has(variant.key) &&
            beforeVariants.find((item) => item.key === variant.key)?.rollout_percentage !== variant.rollout_percentage
    )
    if (splitChanged) {
        lines.push(
            `Variant split ${afterVariants.map((variant) => `${variant.key} ${variant.rollout_percentage}%`).join(', ')}`
        )
    }

    return lines.length ? lines : ['Changed the release conditions']
}

function fieldLabel(field: string): string {
    return field.replace(/_/g, ' ')
}

function describeField(kind: ChangeKind, change: ActivityChange): string[] {
    const { field, before, after } = change
    if (IGNORED_FIELDS.has(field)) {
        return []
    }
    if (kind === 'flag') {
        if (field === 'filters') {
            return describeFilters(before, after)
        }
        if (field === 'active') {
            return [after ? 'Turned on' : 'Turned off']
        }
        if (field === 'key') {
            return [`Changed the key to ${String(after)}`]
        }
        if (field === 'name') {
            return ['Edited the description']
        }
        if (field === 'deleted') {
            return [after ? 'Deleted the flag' : 'Restored the flag']
        }
    }
    if (kind === 'experiment' || kind === 'survey') {
        if (field === 'start_date') {
            return [before ? 'Changed the start date' : 'Launched']
        }
        if (field === 'end_date') {
            return [after ? (kind === 'survey' ? 'Stopped' : 'Ended') : 'Resumed']
        }
        if (field === 'archived') {
            return [after ? 'Archived' : 'Unarchived']
        }
        if (field === 'name') {
            return [`Renamed to ${String(after)}`]
        }
    }
    if (kind === 'experiment') {
        if (field === 'status') {
            return [`Status changed to ${String(after).toLowerCase()}`]
        }
        if (field === 'metrics' || field === 'metrics_secondary') {
            return ['Edited the metrics']
        }
        if (field === 'parameters') {
            return ['Edited the variants']
        }
    }
    if (kind === 'survey') {
        if (field === 'questions') {
            return ['Edited the questions']
        }
        if (field === 'conditions' || field === 'targeting_flag_filters' || field === 'linked_flag') {
            return ['Changed who sees it']
        }
        if (field === 'appearance') {
            return ['Changed how it looks']
        }
    }
    return [`Edited the ${fieldLabel(field)}`]
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
