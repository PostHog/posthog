import { hasKey } from '@/lib/plain-object'

export function isPresentGroupIndex(index: unknown): index is number {
    return typeof index === 'number' && Number.isFinite(index)
}

export function flagLevelGroupIndex(filters: Record<string, unknown> | null | undefined): number | undefined {
    const index = filters?.aggregation_group_type_index
    return isPresentGroupIndex(index) ? index : undefined
}

export function explicitlyClearsAggregation(obj: Record<string, unknown> | null | undefined): boolean {
    return hasKey(obj, 'aggregation_group_type_index') && !isPresentGroupIndex(obj?.aggregation_group_type_index)
}

/** Callers fold an explicit null into `pinnedToPerson` first. `explicitIndex` cannot tell a
 * null from an absent key. */
export function resolveGroupIndex(
    pinnedToPerson: boolean,
    explicitIndex: unknown,
    fallbackIndex: number | undefined
): number | undefined {
    if (pinnedToPerson) {
        return undefined
    }
    return isPresentGroupIndex(explicitIndex) ? explicitIndex : fallbackIndex
}

/** A set with no index of its own aggregates on the flag level, which the API distributes on write. */
export function storedAggregation(group: Record<string, unknown>, flagLevel: number | undefined): number | null {
    return resolveGroupIndex(explicitlyClearsAggregation(group), group.aggregation_group_type_index, flagLevel) ?? null
}
