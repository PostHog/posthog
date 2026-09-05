import { AnyPropertyFilter, FeatureFlagFilters, FeatureFlagGroupType } from '~/types'

export type ConditionSetStatus = 'added' | 'changed' | 'unchanged'
export type ConditionSetAspect = 'criteria' | 'rollout' | 'variant' | 'description'

export interface ConditionSetChange {
    group: FeatureFlagGroupType
    /** Position in the filters after the change. */
    index: number
    status: ConditionSetStatus
    /** The set this one was matched to before the change. Absent for added sets. */
    previous?: FeatureFlagGroupType
}

export interface RemovedConditionSet {
    group: FeatureFlagGroupType
    /** Position in the filters before the change. */
    index: number
}

export interface ReleaseConditionsDiff {
    sets: ConditionSetChange[]
    removed: RemovedConditionSet[]
    /** True when sets that exist on both sides come out in a different order. */
    reordered: boolean
}

interface PropertyFilterShape {
    type?: string
    key?: string
    operator?: string | null
    value?: unknown
    group_type_index?: number | null
}

export function rolloutOf(group: FeatureFlagGroupType): number {
    return group.rollout_percentage ?? 100
}

function propertySignature(property: AnyPropertyFilter): string {
    const { type, key, operator, value, group_type_index } = property as PropertyFilterShape
    return JSON.stringify([type ?? null, key ?? null, operator ?? null, value ?? null, group_type_index ?? null])
}

function criteriaSignature(group: FeatureFlagGroupType): string {
    return JSON.stringify([group.aggregation_group_type_index ?? null, (group.properties ?? []).map(propertySignature)])
}

function setSignature(group: FeatureFlagGroupType): string {
    return JSON.stringify([
        criteriaSignature(group),
        rolloutOf(group),
        group.variant ?? null,
        group.description ?? null,
    ])
}

function propertyKeys(group: FeatureFlagGroupType): string[] {
    return (group.properties ?? []).map((property) => {
        const { type, key } = property as PropertyFilterShape
        return `${type ?? ''}:${key ?? ''}`
    })
}

// Two sets at the same position are treated as one edited set only when they still target the same
// kind of thing. Without this, removing set 1 and appending an unrelated set would read as an edit.
function looksLikeSameSet(a: FeatureFlagGroupType, b: FeatureFlagGroupType): boolean {
    if ((a.aggregation_group_type_index ?? null) !== (b.aggregation_group_type_index ?? null)) {
        return false
    }
    const keysA = propertyKeys(a)
    const keysB = propertyKeys(b)
    if (keysA.length === 0 && keysB.length === 0) {
        return true
    }
    return keysA.some((key) => keysB.includes(key))
}

export function diffReleaseConditionSets(
    before: FeatureFlagFilters | null | undefined,
    after: FeatureFlagFilters
): ReleaseConditionsDiff {
    const beforeGroups = before?.groups ?? []
    const afterGroups = after.groups ?? []
    const beforeSignatures = beforeGroups.map(setSignature)
    const afterSignatures = afterGroups.map(setSignature)
    const beforeCriteria = beforeGroups.map(criteriaSignature)
    const afterCriteria = afterGroups.map(criteriaSignature)

    const matchedBefore = new Map<number, number>()
    const usedBefore = new Set<number>()
    const claim = (afterIndex: number, beforeIndex: number): void => {
        matchedBefore.set(afterIndex, beforeIndex)
        usedBefore.add(beforeIndex)
    }
    const findUnusedBefore = (predicate: (beforeIndex: number) => boolean): number =>
        beforeGroups.findIndex((_, beforeIndex) => !usedBefore.has(beforeIndex) && predicate(beforeIndex))

    afterGroups.forEach((_, afterIndex) => {
        const beforeIndex = findUnusedBefore((j) => beforeSignatures[j] === afterSignatures[afterIndex])
        if (beforeIndex >= 0) {
            claim(afterIndex, beforeIndex)
        }
    })
    afterGroups.forEach((_, afterIndex) => {
        if (matchedBefore.has(afterIndex)) {
            return
        }
        const beforeIndex = findUnusedBefore((j) => beforeCriteria[j] === afterCriteria[afterIndex])
        if (beforeIndex >= 0) {
            claim(afterIndex, beforeIndex)
        }
    })
    afterGroups.forEach((group, afterIndex) => {
        if (matchedBefore.has(afterIndex) || usedBefore.has(afterIndex) || afterIndex >= beforeGroups.length) {
            return
        }
        if (looksLikeSameSet(group, beforeGroups[afterIndex])) {
            claim(afterIndex, afterIndex)
        }
    })
    // A set edited and moved in the same save has no positional partner. Pair it with the one leftover set
    // it still resembles; with several look-alikes there is no safe pick, so those stay added and removed.
    afterGroups.forEach((group, afterIndex) => {
        if (matchedBefore.has(afterIndex)) {
            return
        }
        const candidates = beforeGroups
            .map((_, beforeIndex) => beforeIndex)
            .filter((beforeIndex) => !usedBefore.has(beforeIndex) && looksLikeSameSet(group, beforeGroups[beforeIndex]))
        if (candidates.length === 1) {
            claim(afterIndex, candidates[0])
        }
    })

    const sets: ConditionSetChange[] = afterGroups.map((group, index) => {
        const beforeIndex = matchedBefore.get(index)
        if (beforeIndex === undefined) {
            return { group, index, status: 'added' }
        }
        const status = beforeSignatures[beforeIndex] === afterSignatures[index] ? 'unchanged' : 'changed'
        return { group, index, status, previous: beforeGroups[beforeIndex] }
    })
    const removed = beforeGroups.map((group, index) => ({ group, index })).filter(({ index }) => !usedBefore.has(index))
    const matchedOrder = sets.flatMap((set) => {
        const beforeIndex = matchedBefore.get(set.index)
        return beforeIndex === undefined ? [] : [beforeIndex]
    })
    const reordered = matchedOrder.some(
        (beforeIndex, position) => position > 0 && beforeIndex < matchedOrder[position - 1]
    )

    return { sets, removed, reordered }
}

export function changedAspects(set: ConditionSetChange): ConditionSetAspect[] {
    if (set.status !== 'changed' || !set.previous) {
        return []
    }
    const aspects: ConditionSetAspect[] = []
    if (criteriaSignature(set.previous) !== criteriaSignature(set.group)) {
        aspects.push('criteria')
    }
    if (rolloutOf(set.previous) !== rolloutOf(set.group)) {
        aspects.push('rollout')
    }
    if ((set.previous.variant ?? null) !== (set.group.variant ?? null)) {
        aspects.push('variant')
    }
    if ((set.previous.description ?? null) !== (set.group.description ?? null)) {
        aspects.push('description')
    }
    return aspects
}
