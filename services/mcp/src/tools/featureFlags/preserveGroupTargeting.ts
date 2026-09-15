/**
 * Preserve group-based feature-flag targeting when MCP agents send partial `filters`.
 * Agents rebuild release conditions with only `key` / `operator` / `value`, and the API
 * reads an omitted property `type` as person, which silently converts a group flag to a
 * person flag (PostHog/posthog#46501).
 *
 * `aggregation_group_type_index: null` means person aggregation. Only a missing key is
 * filled from the existing flag.
 *
 * A condition set pinned to person aggregation never gains group targeting. A set is
 * pinned when the payload clears aggregation with an explicit null, or when it carries an
 * explicit person, cohort, or flag property without setting a group index itself. This
 * mirrors check_property_types_match_aggregation in
 * products/feature_flags/backend/filters_validation.py, which rejects a group-aggregated
 * set holding a non-group property.
 *
 * `super_groups` is ignored: the flags API drops it from writes
 * (LEGACY_UNKNOWN_FILTER_KEYS in products/feature_flags/backend/api/filters_schema.py).
 */

export type FlagProperty = {
    key?: string
    type?: string | null
    group_type_index?: number | null
    operator?: string
    value?: unknown
    [key: string]: unknown
}

export type FlagConditionGroup = {
    properties?: FlagProperty[] | null
    rollout_percentage?: number | null
    variant?: string | null
    aggregation_group_type_index?: number | null
    [key: string]: unknown
}

export type FlagFilters = {
    groups?: FlagConditionGroup[] | null
    super_groups?: FlagConditionGroup[] | null
    aggregation_group_type_index?: number | null
    multivariate?: unknown
    payloads?: unknown
    [key: string]: unknown
}

function isPresentType(type: unknown): type is string {
    return typeof type === 'string' && type.length > 0
}

function isPresentGroupIndex(index: unknown): index is number {
    return typeof index === 'number' && Number.isFinite(index)
}

function explicitlyClearsAggregation(obj: Record<string, unknown> | null | undefined): boolean {
    return (
        !!obj &&
        Object.prototype.hasOwnProperty.call(obj, 'aggregation_group_type_index') &&
        !isPresentGroupIndex(obj.aggregation_group_type_index)
    )
}

/** Indexed across all groups so a reordered or collapsed group can still be matched. */
function indexExistingProperties(existing: FlagFilters | null | undefined): Map<string, FlagProperty[]> {
    const map = new Map<string, FlagProperty[]>()
    const groups = existing?.groups
    if (!Array.isArray(groups)) {
        return map
    }
    for (const group of groups) {
        const props = group?.properties
        if (!Array.isArray(props)) {
            continue
        }
        for (const prop of props) {
            if (!prop || typeof prop.key !== 'string' || prop.key.length === 0) {
                continue
            }
            const list = map.get(prop.key) ?? []
            list.push(prop)
            map.set(prop.key, list)
        }
    }
    return map
}

function pickMatchingExisting(
    candidates: FlagProperty[] | undefined,
    incoming: FlagProperty
): FlagProperty | undefined {
    if (!candidates || candidates.length === 0) {
        return undefined
    }
    if (incoming.operator) {
        const byOp = candidates.find((c) => c.operator === incoming.operator)
        if (byOp) {
            return byOp
        }
    }
    return candidates.find((c) => c.type === 'group') ?? candidates[0]
}

function resolveGroupIndex(
    pinnedToPerson: boolean,
    explicitIndex: unknown,
    fallbackIndex: number | undefined
): number | undefined {
    if (pinnedToPerson) {
        return undefined
    }
    return isPresentGroupIndex(explicitIndex) ? explicitIndex : fallbackIndex
}

function mergeProperty(
    incoming: FlagProperty,
    existingProp: FlagProperty | undefined,
    fallbackGroupTypeIndex: number | undefined,
    canCarryGroupTargeting: boolean
): FlagProperty {
    const out: FlagProperty = { ...incoming }

    if (!isPresentType(out.type) && existingProp && isPresentType(existingProp.type)) {
        // Leaving the type unset makes the API report the property the agent actually
        // sent. Restoring `group` here would name fields the agent never sent.
        // `!== 'group'` relies on the same complement rule. See mergeConditionGroup.
        if (canCarryGroupTargeting || existingProp.type !== 'group') {
            out.type = existingProp.type
        }
    }

    if (canCarryGroupTargeting && !isPresentType(out.type) && isPresentGroupIndex(fallbackGroupTypeIndex)) {
        out.type = 'group'
    }

    if (out.type === 'group' && !isPresentGroupIndex(out.group_type_index)) {
        if (existingProp && isPresentGroupIndex(existingProp.group_type_index)) {
            out.group_type_index = existingProp.group_type_index
        } else if (isPresentGroupIndex(fallbackGroupTypeIndex)) {
            out.group_type_index = fallbackGroupTypeIndex
        }
    }

    return out
}

type MergeConditionOptions = {
    /** Restore set-level aggregation only from a same-index existing group (not a fallback group). */
    allowAggregationRestore: boolean
    /** The payload cleared aggregation with an explicit null, so no group index is restored. */
    incomingClearsAggregation: boolean
}

function mergeConditionGroup(
    incoming: FlagConditionGroup,
    propertySourceGroup: FlagConditionGroup | undefined,
    flagLevelGroupIndex: number | undefined,
    crossGroupPropsByKey: Map<string, FlagProperty[]>,
    options: MergeConditionOptions
): FlagConditionGroup {
    const out: FlagConditionGroup = { ...incoming }

    // One explicit person, cohort, or flag property stops this set from keeping or
    // gaining group targeting. An explicit incoming group index still wins, and the API
    // then reports the contradiction in the agent's own payload.
    // `!== 'group'` is the complement of PERSON_AGGREGATED_PROPERTY_TYPES in
    // filters_validation.py. It holds only while 'group' is the sole type outside that
    // tuple. A Python test asserts that:
    // products/feature_flags/backend/test/test_filters_validation.py
    const hasExplicitNonGroupProperty =
        Array.isArray(incoming.properties) &&
        incoming.properties.some((p) => isPresentType(p?.type) && p.type !== 'group')
    const propertiesPinSetToPerson =
        hasExplicitNonGroupProperty && !isPresentGroupIndex(out.aggregation_group_type_index)
    if (propertiesPinSetToPerson) {
        out.aggregation_group_type_index = null
    }

    const pinnedToPerson = options.incomingClearsAggregation || propertiesPinSetToPerson

    // Fill only when the key is absent. An explicit null means person aggregation.
    if (
        options.allowAggregationRestore &&
        !pinnedToPerson &&
        !Object.prototype.hasOwnProperty.call(out, 'aggregation_group_type_index') &&
        propertySourceGroup &&
        isPresentGroupIndex(propertySourceGroup.aggregation_group_type_index)
    ) {
        out.aggregation_group_type_index = propertySourceGroup.aggregation_group_type_index
    }

    const effectiveGroupIndex = resolveGroupIndex(pinnedToPerson, out.aggregation_group_type_index, flagLevelGroupIndex)

    if (Array.isArray(out.properties)) {
        const sameGroupByKey = new Map<string, FlagProperty[]>()
        if (Array.isArray(propertySourceGroup?.properties)) {
            for (const p of propertySourceGroup.properties) {
                if (p && typeof p.key === 'string') {
                    const list = sameGroupByKey.get(p.key) ?? []
                    list.push(p)
                    sameGroupByKey.set(p.key, list)
                }
            }
        }

        out.properties = out.properties.map((prop) => {
            if (!prop || typeof prop !== 'object') {
                return prop
            }
            if (typeof prop.key !== 'string') {
                return prop
            }
            // Cross-group matching covers groups the payload reordered or collapsed.
            const existingProp =
                pickMatchingExisting(sameGroupByKey.get(prop.key), prop) ??
                pickMatchingExisting(crossGroupPropsByKey.get(prop.key), prop)
            return mergeProperty(prop, existingProp, effectiveGroupIndex, !pinnedToPerson)
        })
    }

    return out
}

/**
 * Merge incoming MCP filters with the flag's current filters. Explicitly set incoming
 * values always win, `null` included. Only missing `type`, `group_type_index`, and
 * `aggregation_group_type_index` keys are filled from the existing flag.
 */
export function preserveGroupTargetingFilters(
    existing: FlagFilters | null | undefined,
    incoming: FlagFilters | null | undefined
): FlagFilters | null | undefined {
    if (!incoming || typeof incoming !== 'object') {
        return incoming
    }

    const result: FlagFilters = { ...incoming }

    const existingFlagGroupIndex = isPresentGroupIndex(existing?.aggregation_group_type_index)
        ? existing!.aggregation_group_type_index!
        : undefined

    const incomingClearsAggregation = explicitlyClearsAggregation(incoming as Record<string, unknown>)

    // The flag-level index is the UI's "Target by" group type.
    if (
        !incomingClearsAggregation &&
        !Object.prototype.hasOwnProperty.call(result, 'aggregation_group_type_index') &&
        isPresentGroupIndex(existingFlagGroupIndex)
    ) {
        result.aggregation_group_type_index = existingFlagGroupIndex
    }

    const effectiveFlagGroupIndex = resolveGroupIndex(
        incomingClearsAggregation,
        result.aggregation_group_type_index,
        existingFlagGroupIndex
    )

    if (Array.isArray(result.groups)) {
        const crossGroupPropsByKey = indexExistingProperties(existing)
        const existingGroups = Array.isArray(existing?.groups) ? existing!.groups! : []
        result.groups = result.groups.map((group, index) => {
            if (!group || typeof group !== 'object') {
                return group
            }

            const sameIndexGroup = existingGroups[index]
            // Aggregation restores only from the same index, so appending a person set
            // cannot inherit another set's group index. Property restore is looser.
            const propertySourceGroup =
                sameIndexGroup ??
                existingGroups.find((g) => isPresentGroupIndex(g?.aggregation_group_type_index)) ??
                existingGroups[0]

            const groupClearsAggregation = explicitlyClearsAggregation(group as Record<string, unknown>)

            return mergeConditionGroup(group, propertySourceGroup, effectiveFlagGroupIndex, crossGroupPropsByKey, {
                allowAggregationRestore: sameIndexGroup !== undefined,
                // A flag-level clear only pins sets that omit the key. A set that carries its own
                // index keeps it, which matches the backend's per-set fallback in filters_validation.py.
                incomingClearsAggregation:
                    groupClearsAggregation ||
                    (incomingClearsAggregation && !isPresentGroupIndex(group.aggregation_group_type_index)),
            })
        })
    }

    return result
}
