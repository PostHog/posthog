import { createHash } from 'node:crypto'

import { canonicalJson, isRecord } from '@/lib/plain-object'

import { flagLevelGroupIndex, storedAggregation } from './aggregation'

/**
 * The ID covers only what the update merge restores from: the key, type, group_type_index,
 * operator, and value of each property, and the aggregation the condition uses.
 * An edit to rollout, variant, or description between an agent's read and its write keeps the ID.
 * A read-time annotation such as cohort_name does not change it either. Two stored conditions with
 * the same ID restore the same types, so the merge does not need to tell them apart.
 *
 * A condition without an aggregation_group_type_index key aggregates on the flag level. Every API
 * write that sends filters copies the flag level into each such condition (validate_filters in
 * products/feature_flags/backend/api/feature_flag.py). Hashing the resolved aggregation keeps that
 * write from changing the ID.
 */
export function conditionId(group: Record<string, unknown>, flagLevel: number | undefined): string {
    const aggregation = storedAggregation(group, flagLevel)
    const properties = Array.isArray(group.properties) ? group.properties.filter(isRecord) : []
    const filters = properties
        .map((prop) =>
            canonicalJson([
                prop.key,
                prop.type ?? null,
                prop.group_type_index ?? null,
                prop.operator ?? null,
                prop.value ?? null,
            ])
        )
        .sort()
    return createHash('sha256')
        .update(canonicalJson([aggregation, filters]))
        .digest('hex')
        .slice(0, 16)
}

/**
 * Accepts a flag, a record that holds a flag under `feature_flag` (an experiment or a my-flags
 * row), or a list of either as an array or under `results`. Any other value passes through.
 */
export function withConditionIds<T>(value: T): T {
    if (Array.isArray(value)) {
        return value.map(withConditionIds) as T
    }
    if (!isRecord(value)) {
        return value
    }
    if (Array.isArray(value.results)) {
        return { ...value, results: value.results.map(withConditionIds) }
    }
    if (isRecord(value.feature_flag)) {
        return { ...value, feature_flag: withConditionIds(value.feature_flag) }
    }
    if (!isRecord(value.filters) || !Array.isArray(value.filters.groups)) {
        return value
    }
    const flagLevel = flagLevelGroupIndex(value.filters)
    const groups = value.filters.groups.map((group: unknown) => {
        if (!isRecord(group)) {
            return group
        }
        const { condition_id: _stored, ...rest } = group
        return { condition_id: conditionId(group, flagLevel), ...rest }
    })
    return { ...value, filters: { ...value.filters, groups } }
}
