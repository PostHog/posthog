import type { FlagConditionGroup, FlagFilters, FlagProperty } from './preserveGroupTargeting'

export type PropertyChange = {
    key: string
    operator?: string
    values_added?: unknown[]
    values_removed?: unknown[]
    value_before?: unknown
    value_after?: unknown
}

export type ConditionChange = {
    index: number
    properties_added: FlagProperty[]
    properties_removed: FlagProperty[]
    properties_changed: PropertyChange[]
    rollout_before: number
    rollout_after: number
    order_changed?: boolean
}

export type FiltersChange = {
    changed: boolean
    narrows: boolean
    conditions_added: number[]
    conditions_removed: number[]
    conditions_changed: ConditionChange[]
    summary: string
}

type NormalizedProperty = {
    raw: FlagProperty
    key: string
    operator: string | null
    value: unknown
    identity: string
    signature: string
}

type NormalizedCondition = {
    index: number
    properties: NormalizedProperty[]
    rollout: number
    variant: string | null
    aggregationGroupTypeIndex: number | null
    signature: string
}

type ChangedCondition = {
    change: ConditionChange
    before: NormalizedCondition
    after: NormalizedCondition
}

type Matching<T> = {
    pairs: Array<[T, T]>
    unmatchedBefore: T[]
    unmatchedAfter: T[]
}

function stableStringify(value: unknown): string {
    if (Array.isArray(value)) {
        return `[${value.map((item) => stableStringify(item)).join(',')}]`
    }
    if (value !== null && typeof value === 'object') {
        const record = value as Record<string, unknown>
        const keys = Object.keys(record)
            .filter((key) => record[key] !== undefined)
            .sort()
        return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(',')}}`
    }
    return JSON.stringify(value ?? null)
}

function valueSignature(value: unknown): string {
    if (Array.isArray(value)) {
        return `[${value
            .map((item) => stableStringify(item))
            .sort()
            .join(',')}]`
    }
    return stableStringify(value)
}

function normalizeProperty(raw: FlagProperty): NormalizedProperty {
    const key = typeof raw.key === 'string' ? raw.key : ''
    const type = typeof raw.type === 'string' && raw.type.length > 0 ? raw.type : 'person'
    const groupTypeIndex = typeof raw.group_type_index === 'number' ? raw.group_type_index : null
    const operator = typeof raw.operator === 'string' ? raw.operator : null
    const value = raw.value ?? null
    const identity = stableStringify([key, type, groupTypeIndex, operator])
    return { raw, key, operator, value, identity, signature: `${identity}:${valueSignature(value)}` }
}

function normalizeCondition(raw: FlagConditionGroup | null | undefined, index: number): NormalizedCondition {
    const group: FlagConditionGroup = raw ?? {}
    const properties = Array.isArray(group.properties)
        ? group.properties
              .filter((property) => property !== null && typeof property === 'object')
              .map((property) => normalizeProperty(property))
        : []
    const rollout = typeof group.rollout_percentage === 'number' ? group.rollout_percentage : 100
    const variant = typeof group.variant === 'string' ? group.variant : null
    const aggregationGroupTypeIndex =
        typeof group.aggregation_group_type_index === 'number' ? group.aggregation_group_type_index : null
    const signature = stableStringify([
        variant,
        aggregationGroupTypeIndex,
        properties.map((property) => property.signature).sort(),
    ])
    return { index, properties, rollout, variant, aggregationGroupTypeIndex, signature }
}

function normalizeGroups(filters: FlagFilters | null | undefined): NormalizedCondition[] {
    const groups = filters?.groups
    return Array.isArray(groups) ? groups.map((group, index) => normalizeCondition(group, index)) : []
}

function matchInOrder<T>(before: T[], after: T[], passes: Array<(previous: T, next: T) => boolean>): Matching<T> {
    const unmatchedBefore = new Set(before)
    const unmatchedAfter = new Set(after)
    const pairs: Array<[T, T]> = []
    for (const isSame of passes) {
        for (const next of after) {
            if (!unmatchedAfter.has(next)) {
                continue
            }
            const previous = before.find((candidate) => unmatchedBefore.has(candidate) && isSame(candidate, next))
            if (previous !== undefined) {
                unmatchedBefore.delete(previous)
                unmatchedAfter.delete(next)
                pairs.push([previous, next])
            }
        }
    }
    return {
        pairs,
        unmatchedBefore: before.filter((item) => unmatchedBefore.has(item)),
        unmatchedAfter: after.filter((item) => unmatchedAfter.has(item)),
    }
}

function zip<T>(left: T[], right: T[]): Array<[T, T]> {
    const pairs: Array<[T, T]> = []
    left.forEach((item, position) => {
        const partner = right[position]
        if (partner !== undefined) {
            pairs.push([item, partner])
        }
    })
    return pairs
}

function describePropertyChange(previous: NormalizedProperty, next: NormalizedProperty): PropertyChange {
    const change: PropertyChange = { key: next.key }
    if (next.operator !== null) {
        change.operator = next.operator
    }
    if (Array.isArray(previous.value) && Array.isArray(next.value)) {
        const beforeValues = new Set(previous.value.map((value) => stableStringify(value)))
        const afterValues = new Set(next.value.map((value) => stableStringify(value)))
        change.values_added = next.value.filter((value) => !beforeValues.has(stableStringify(value)))
        change.values_removed = previous.value.filter((value) => !afterValues.has(stableStringify(value)))
    } else {
        change.value_before = previous.value
        change.value_after = next.value
    }
    return change
}

function diffProperties(
    before: NormalizedProperty[],
    after: NormalizedProperty[]
): Pick<ConditionChange, 'properties_added' | 'properties_removed' | 'properties_changed'> {
    const matching = matchInOrder(before, after, [
        (previous, next) => previous.signature === next.signature,
        (previous, next) => previous.identity === next.identity,
    ])
    return {
        properties_added: matching.unmatchedAfter.map((property) => property.raw),
        properties_removed: matching.unmatchedBefore.map((property) => property.raw),
        properties_changed: matching.pairs
            .filter(([previous, next]) => previous.signature !== next.signature)
            .map(([previous, next]) => describePropertyChange(previous, next)),
    }
}

function describeConditionPair(before: NormalizedCondition, after: NormalizedCondition): ConditionChange {
    return {
        index: after.index,
        ...diffProperties(before.properties, after.properties),
        rollout_before: before.rollout,
        rollout_after: after.rollout,
    }
}

function scalarValues(value: unknown): Set<string> {
    return new Set((Array.isArray(value) ? value : [value]).map((item) => stableStringify(item)))
}

function propertyChangeNarrows(change: PropertyChange): boolean {
    if (change.operator === 'exact' || change.operator === 'is_not') {
        const before = scalarValues(change.value_before)
        const after = scalarValues(change.value_after)
        const valuesAdded = change.values_added ?? [...after].filter((value) => !before.has(value))
        const valuesRemoved = change.values_removed ?? [...before].filter((value) => !after.has(value))
        return change.operator === 'exact' ? valuesRemoved.length > 0 : valuesAdded.length > 0
    }
    // The effect of other operators cannot be inferred safely; do not report a false negative.
    return (
        change.value_before !== undefined ||
        change.value_after !== undefined ||
        (change.values_added?.length ?? 0) > 0 ||
        (change.values_removed?.length ?? 0) > 0
    )
}

function propertyChangeWidens(change: PropertyChange): boolean {
    if (change.operator === 'exact' || change.operator === 'is_not') {
        const before = scalarValues(change.value_before)
        const after = scalarValues(change.value_after)
        const valuesAdded = change.values_added ?? [...after].filter((value) => !before.has(value))
        const valuesRemoved = change.values_removed ?? [...before].filter((value) => !after.has(value))
        return change.operator === 'exact' ? valuesAdded.length > 0 : valuesRemoved.length > 0
    }
    return (
        change.value_before !== undefined ||
        change.value_after !== undefined ||
        (change.values_added?.length ?? 0) > 0 ||
        (change.values_removed?.length ?? 0) > 0
    )
}

function conditionNarrows(change: ConditionChange, before?: NormalizedCondition, after?: NormalizedCondition): boolean {
    return (
        change.properties_added.length > 0 ||
        change.properties_changed.some((property) => propertyChangeNarrows(property)) ||
        change.rollout_after < change.rollout_before ||
        change.order_changed === true ||
        (before !== undefined &&
            after !== undefined &&
            (before.variant !== after.variant || before.aggregationGroupTypeIndex !== after.aggregationGroupTypeIndex))
    )
}

function conditionWidens(change: ConditionChange, before?: NormalizedCondition, after?: NormalizedCondition): boolean {
    return (
        change.properties_removed.length > 0 ||
        change.properties_changed.some((property) => propertyChangeWidens(property)) ||
        change.rollout_after > change.rollout_before ||
        (before !== undefined &&
            after !== undefined &&
            (before.variant !== after.variant || before.aggregationGroupTypeIndex !== after.aggregationGroupTypeIndex))
    )
}

function formatValue(value: unknown): string {
    if (Array.isArray(value)) {
        const shown = value.slice(0, 3).map((item) => stableStringify(item))
        return `[${shown.join(', ')}${value.length > 3 ? ', ...' : ''}]`
    }
    return stableStringify(value)
}

function formatProperty(property: FlagProperty): string {
    const { key, operator, value } = normalizeProperty(property)
    return `\`${[key, operator, formatValue(value)].filter((part) => part !== null).join(' ')}\``
}

function formatFilterLabel(change: PropertyChange): string {
    return `\`${change.operator ? `${change.key} ${change.operator}` : change.key}\``
}

function joinClauses(clauses: string[]): string {
    if (clauses.length <= 1) {
        return clauses.join('')
    }
    return `${clauses.slice(0, -1).join(', ')} and ${clauses[clauses.length - 1]}`
}

function listConditions(indexes: number[]): string {
    const numbers = indexes.map((index) => String(index + 1))
    return `${numbers.length === 1 ? 'Condition' : 'Conditions'} ${joinClauses(numbers)}`
}

function describeConditionClauses(entry: ChangedCondition): string[] {
    const { change, before, after } = entry
    const clauses: string[] = []
    for (const property of change.properties_added) {
        clauses.push(`gained the filter ${formatProperty(property)}`)
    }
    for (const property of change.properties_removed) {
        clauses.push(`lost the filter ${formatProperty(property)}`)
    }
    for (const property of change.properties_changed) {
        const label = formatFilterLabel(property)
        if (property.values_added || property.values_removed) {
            if (property.values_added && property.values_added.length > 0) {
                clauses.push(`added ${formatValue(property.values_added)} to ${label}`)
            }
            if (property.values_removed && property.values_removed.length > 0) {
                clauses.push(`removed ${formatValue(property.values_removed)} from ${label}`)
            }
        } else {
            clauses.push(
                `changed ${label} from ${formatValue(property.value_before)} to ${formatValue(property.value_after)}`
            )
        }
    }
    if (change.rollout_before !== change.rollout_after) {
        clauses.push(`moved its rollout from ${change.rollout_before}% to ${change.rollout_after}%`)
    }
    if (before.variant !== after.variant) {
        clauses.push(`now serves variant ${formatValue(after.variant)} instead of ${formatValue(before.variant)}`)
    }
    if (before.aggregationGroupTypeIndex !== after.aggregationGroupTypeIndex) {
        clauses.push(
            `now targets group type ${formatValue(after.aggregationGroupTypeIndex)} instead of ${formatValue(before.aggregationGroupTypeIndex)}`
        )
    }
    if (change.order_changed) {
        clauses.push('moved earlier while early exit is enabled')
    }
    if (clauses.length === 0) {
        clauses.push('changed')
    }
    return clauses
}

function describeChangedCondition(entry: ChangedCondition): string {
    const narrows = conditionNarrows(entry.change, entry.before, entry.after)
    const widens = conditionWidens(entry.change, entry.before, entry.after)
    const effect =
        narrows && widens
            ? ', so its access may have changed'
            : narrows
              ? ', so it now serves fewer users'
              : widens
                ? ', so it now serves more users'
                : ''
    return `Condition ${entry.change.index + 1} ${joinClauses(describeConditionClauses(entry))}${effect}.`
}

function buildSummary(
    added: number[],
    removed: number[],
    changed: ChangedCondition[],
    zeroRolloutAdded: number[],
    earlyExitAdded: number[]
): string {
    const sentences: Array<{ text: string; narrows: boolean }> = []
    if (added.length > 0) {
        const zeroRollout = new Set(zeroRolloutAdded)
        const earlyExit = new Set(earlyExitAdded)
        const servingNobody = added.filter((index) => zeroRollout.has(index) && !earlyExit.has(index))
        const servingUsers = added.filter((index) => !zeroRollout.has(index) && !earlyExit.has(index))
        const mayStopLaterConditions = added.filter((index) => earlyExit.has(index))
        if (servingUsers.length > 0) {
            sentences.push({
                text: `${listConditions(servingUsers)} ${servingUsers.length === 1 ? 'is' : 'are'} new, so the flag now serves more users.`,
                narrows: false,
            })
        }
        if (servingNobody.length > 0) {
            sentences.push({
                text: `${listConditions(servingNobody)} ${servingNobody.length === 1 ? 'is' : 'are'} new with 0% rollout, so ${servingNobody.length === 1 ? 'it serves' : 'they serve'} nobody and block nobody.`,
                narrows: false,
            })
        }
        if (mayStopLaterConditions.length > 0) {
            sentences.push({
                text: `${listConditions(mayStopLaterConditions)} ${mayStopLaterConditions.length === 1 ? 'has' : 'have'} rollout below 100% while early exit is enabled, so ${mayStopLaterConditions.length === 1 ? 'it may' : 'they may'} stop later conditions and access may have changed.`,
                narrows: true,
            })
        }
    }
    if (removed.length > 0) {
        sentences.push({
            text: `Previous ${listConditions(removed).toLowerCase()} ${removed.length === 1 ? 'was' : 'were'} removed, so the flag now serves fewer users.`,
            narrows: true,
        })
    }
    for (const entry of changed) {
        sentences.push({
            text: describeChangedCondition(entry),
            narrows: conditionNarrows(entry.change, entry.before, entry.after),
        })
    }
    if (sentences.length === 0) {
        return 'Release conditions did not change.'
    }
    if (sentences.length <= 3) {
        return sentences.map((sentence) => sentence.text).join(' ')
    }
    const narrowing = sentences.filter((sentence) => sentence.narrows)
    const others = sentences.filter((sentence) => !sentence.narrows)
    // Always name every condition that may have lost access, even in a long response.
    const shown = [...narrowing, ...others.slice(0, Math.max(0, 2 - narrowing.length))]
    return `${shown.map((sentence) => sentence.text).join(' ')} ${sentences.length - shown.length} more changes are listed in conditions_added, conditions_removed and conditions_changed.`
}

const MAX_CONDITIONS_TO_SUMMARIZE = 500

export function describeFiltersChange(
    previous: FlagFilters | null | undefined,
    next: FlagFilters | null | undefined
): FiltersChange {
    const beforeGroups = normalizeGroups(previous)
    const afterGroups = normalizeGroups(next)
    if (beforeGroups.length > MAX_CONDITIONS_TO_SUMMARIZE || afterGroups.length > MAX_CONDITIONS_TO_SUMMARIZE) {
        return {
            changed: true,
            narrows: true,
            conditions_added: [],
            conditions_removed: [],
            conditions_changed: [],
            summary:
                'There are too many release conditions to summarize safely; review the targeting change before confirming it.',
        }
    }
    const matching = matchInOrder(beforeGroups, afterGroups, [
        (before, after) => before.signature === after.signature && before.rollout === after.rollout,
        (before, after) => before.signature === after.signature,
    ])
    const positionalPairs = zip(matching.unmatchedBefore, matching.unmatchedAfter)
    const earlyExit = previous?.early_exit === true || next?.early_exit === true
    const changedConditions: ChangedCondition[] = [...matching.pairs, ...positionalPairs]
        .filter(
            ([before, after]) =>
                before.signature !== after.signature ||
                before.rollout !== after.rollout ||
                (earlyExit && before.index > after.index && after.rollout < 100)
        )
        .map(([before, after]) => {
            const change = describeConditionPair(before, after)
            if (earlyExit && before.index > after.index && after.rollout < 100) {
                change.order_changed = true
            }
            return { before, after, change }
        })
        .sort((left, right) => left.change.index - right.change.index)
    const addedConditions = matching.unmatchedAfter.slice(positionalPairs.length)
    const conditionsAdded = addedConditions.map((condition) => condition.index)
    const conditionsRemoved = matching.unmatchedBefore.slice(positionalPairs.length).map((condition) => condition.index)
    const conditionsChanged = changedConditions.map((entry) => entry.change)
    return {
        changed: conditionsAdded.length > 0 || conditionsRemoved.length > 0 || conditionsChanged.length > 0,
        narrows:
            conditionsRemoved.length > 0 ||
            (earlyExit && addedConditions.some((condition) => condition.rollout < 100)) ||
            changedConditions.some((entry) => conditionNarrows(entry.change, entry.before, entry.after)),
        conditions_added: conditionsAdded,
        conditions_removed: conditionsRemoved,
        conditions_changed: conditionsChanged,
        summary: buildSummary(
            conditionsAdded,
            conditionsRemoved,
            changedConditions,
            addedConditions.filter((condition) => condition.rollout === 0).map((condition) => condition.index),
            earlyExit
                ? addedConditions.filter((condition) => condition.rollout < 100).map((condition) => condition.index)
                : []
        ),
    }
}
