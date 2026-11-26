import { ToolInputValidationError } from '@/lib/errors'
import { canonicalJson, hasKey, isRecord } from '@/lib/plain-object'

import { flagLevelGroupIndex } from './aggregation'
import { conditionId } from './conditionIds'
import type { FlagFilters } from './preserveGroupTargeting'

type Group = Record<string, unknown>

/**
 * `update-feature-flag` replaces the whole `filters` object, so a condition sent without `description`
 * loses its stored name. A condition that carries a `condition_id` and no `description` key takes the
 * description of the stored condition it continues. An explicit null or empty string still clears it.
 *
 * The ID does not cover variant, rollout, or description, so several stored conditions can share one.
 * A condition first looks among stored conditions with its ID, variant, and rollout, then among those with
 * its ID. It takes their description when they all have the same one, or else the description at its own
 * position when it and the stored conditions are equal in number. Otherwise the update is refused.
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
    const stored = storedGroups.filter(isRecord).map((group) => ({ group, id: conditionId(group, flagLevel) }))
    const sent = incoming.groups.flatMap((group) =>
        isRecord(group) && typeof group.condition_id === 'string' ? [{ group, id: group.condition_id }] : []
    )
    const keys = [
        ({ group, id }: { group: Group; id: string }) =>
            canonicalJson([id, group.variant ?? null, group.rollout_percentage ?? null]),
        ({ id }: { id: string }) => id,
    ]

    const ambiguous: number[] = []
    const groups = incoming.groups.map((group, index) => {
        if (!isRecord(group) || typeof group.condition_id !== 'string' || hasKey(group, 'description')) {
            return group
        }
        const self = { group, id: group.condition_id }
        for (const key of keys) {
            const matches = stored.filter((candidate) => key(candidate) === key(self))
            if (matches.length === 0) {
                continue
            }
            const descriptions = matches.map(({ group }) => group.description ?? null)
            const peers = sent.filter((candidate) => key(candidate) === key(self))
            const description = descriptions.every((d) => d === descriptions[0])
                ? descriptions[0]
                : peers.length === matches.length
                  ? descriptions[peers.findIndex((peer) => peer.group === group)]
                  : undefined
            if (description !== undefined) {
                return typeof description === 'string' ? { ...group, description } : group
            }
        }
        // A condition_id that matches no stored condition is refused later as stale.
        if (stored.some(({ id }) => id === group.condition_id)) {
            ambiguous.push(index)
        }
        return group
    })
    if (ambiguous.length > 0) {
        const paths = ambiguous.map((index) => `filters.groups[${index}]`).join(', ')
        throw new ToolInputValidationError(
            `${paths} share a condition_id with stored conditions that have different descriptions, so this ` +
                'tool cannot tell which name each one keeps. Send `description` on every condition with that ' +
                'condition_id.',
            { fields: ['filters.groups.N.description:ambiguous_description'] }
        )
    }
    return { ...incoming, groups }
}
