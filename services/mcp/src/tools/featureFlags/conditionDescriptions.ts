import { hasKey, isRecord } from '@/lib/plain-object'

import { flagLevelGroupIndex } from './aggregation'
import { conditionId } from './conditionIds'
import type { FlagFilters } from './preserveGroupTargeting'

/**
 * `update-feature-flag` replaces the whole `filters` object, so a condition sent without `description`
 * loses its stored name. A condition that carries a `condition_id` and no `description` key takes the
 * description of the stored condition with that ID. An explicit null or empty string still clears it.
 *
 * The ID does not cover the description, so two stored conditions can share an ID and have different
 * descriptions. Such a condition takes the description of the stored condition at its own index when that
 * one has the ID. Otherwise it takes a description only when all stored conditions with the ID have the same one.
 * Run this before preserveGroupTargetingFilters, which removes each `condition_id`.
 */
export function restoreConditionDescriptions(
    existing: FlagFilters | null | undefined,
    incoming: FlagFilters | null | undefined
): FlagFilters | null | undefined {
    const storedGroups = existing?.groups
    if (!isRecord(incoming) || !Array.isArray(incoming.groups) || !Array.isArray(storedGroups)) {
        return incoming
    }
    const flagLevel = flagLevelGroupIndex(existing)
    const storedIds = storedGroups.map((group) => (isRecord(group) ? conditionId(group, flagLevel) : undefined))
    const storedDescription = (id: string, index: number): unknown => {
        if (storedIds[index] === id) {
            return storedGroups[index]?.description
        }
        const descriptions = new Set(
            storedGroups.flatMap((group, storedIndex) => (storedIds[storedIndex] === id ? [group?.description] : []))
        )
        return descriptions.size === 1 ? [...descriptions][0] : undefined
    }
    const groups = incoming.groups.map((group, index) => {
        if (!isRecord(group) || typeof group.condition_id !== 'string' || hasKey(group, 'description')) {
            return group
        }
        const description = storedDescription(group.condition_id, index)
        return typeof description === 'string' ? { ...group, description } : group
    })
    return { ...incoming, groups }
}
