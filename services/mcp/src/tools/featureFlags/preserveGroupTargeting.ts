/**
 * Preserve group-based feature-flag targeting when MCP agents send partial `filters`.
 *
 * Background (PostHog/posthog#46501):
 * Agents often rebuild release conditions with only `key` / `operator` / `value`.
 * The API treats omitted property `type` as person, and omitted
 * `aggregation_group_type_index` drops group-level targeting. That silently
 * corrupts flags that target groups (e.g. workspaces / segment_group).
 *
 * When the agent supplies `filters` on update, merge in group-targeting fields
 * from the existing flag whenever the incoming payload left them unset.
 *
 * Note on `super_groups`: a legacy pre-`holdout` key. Stored flags may still
 * carry it, but the flags API drops it from writes (LEGACY_UNKNOWN_FILTER_KEYS
 * in products/feature_flags/backend/api/filters_schema.py), so there is no
 * group targeting under it worth preserving and this helper ignores it.
 *
 * Explicit null: `aggregation_group_type_index: null` means person-level
 * aggregation (API/docs). Only a missing key is treated as "fill from existing".
 *
 * A condition set pinned to person aggregation never gains group targeting from
 * the existing flag. A set is pinned when the payload clears aggregation with an
 * explicit null, or when it carries any explicit person/cohort/flag property
 * without setting a group index itself. The API rejects a group-aggregated set
 * that holds a non-group property (validated in
 * products/feature_flags/backend/api/feature_flag.py), so filling group fields
 * into a pinned set would only produce a 400 naming fields the agent never sent.
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
    /** Legacy pre-holdout key — ignored on write by the flags API; not rewritten here. */
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

/** True when the payload explicitly set aggregation_group_type_index to null/undefined (person). */
function explicitlyClearsAggregation(obj: Record<string, unknown> | null | undefined): boolean {
    return (
        !!obj &&
        Object.prototype.hasOwnProperty.call(obj, 'aggregation_group_type_index') &&
        !isPresentGroupIndex(obj.aggregation_group_type_index)
    )
}

/**
 * Build a lookup of existing properties by key across all condition groups
 * so we can restore type / group_type_index when groups are reordered/replaced.
 */
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
    // Prefer a group-typed property when restoring ambiguity.
    return candidates.find((c) => c.type === 'group') ?? candidates[0]
}

/** The group index a set or flag effectively targets: its own explicit index, else the inherited fallback. */
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
        // Restoring `group` into a pinned set produces a 400 about group properties
        // the agent never sent. Leave the type unset so the API reports the
        // property that is actually in the payload.
        if (canCarryGroupTargeting || existingProp.type !== 'group') {
            out.type = existingProp.type
        }
    }

    // If this condition set is group-aggregated and type is still missing, prefer group.
    if (canCarryGroupTargeting && !isPresentType(out.type) && isPresentGroupIndex(fallbackGroupTypeIndex)) {
        out.type = 'group'
    }

    // Only attach group_type_index when this property is (or becomes) group-typed.
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
    /** Incoming set explicitly cleared aggregation (null) — do not restore group index. */
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

    // The API rejects a group-aggregated condition set that holds any non-group
    // property, so one explicit person/cohort/flag property is enough to stop this
    // set from keeping or gaining group targeting. An explicit incoming group index
    // still wins, and the API then reports the contradiction in the agent's payload.
    const hasExplicitNonGroupProperty =
        Array.isArray(incoming.properties) &&
        incoming.properties.some((p) => isPresentType(p?.type) && p.type !== 'group')
    const propertiesPinSetToPerson =
        hasExplicitNonGroupProperty && !isPresentGroupIndex(out.aggregation_group_type_index)
    if (propertiesPinSetToPerson) {
        out.aggregation_group_type_index = null
    }

    const pinnedToPerson = options.incomingClearsAggregation || propertiesPinSetToPerson

    // Prefer explicit incoming aggregation; only fill when the key is absent
    // (not when it is explicitly null = person aggregation).
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
            // Same-group match first, then cross-group-by-key (reordered/collapsed groups).
            const existingProp =
                pickMatchingExisting(sameGroupByKey.get(prop.key), prop) ??
                pickMatchingExisting(crossGroupPropsByKey.get(prop.key), prop)
            return mergeProperty(prop, existingProp, effectiveGroupIndex, !pinnedToPerson)
        })
    }

    return out
}

/**
 * Merge incoming MCP filters with the flag's current filters so group targeting
 * is not silently demoted to person targeting.
 *
 * Incoming values always win when explicitly set (including `null` for person
 * aggregation). Only *missing* type / group_type_index / aggregation_group_type_index
 * keys are filled from existing.
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

    // Preserve flag-level group aggregation (UI "Target by" group type) only when
    // the key is omitted — not when agents send explicit null (person targeting).
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
            // Property restore may use a fallback group; aggregation restore only
            // from same-index so appending a person set does not inherit org index.
            const propertySourceGroup =
                sameIndexGroup ??
                existingGroups.find((g) => isPresentGroupIndex(g?.aggregation_group_type_index)) ??
                existingGroups[0]

            const groupClearsAggregation = explicitlyClearsAggregation(group as Record<string, unknown>)

            return mergeConditionGroup(group, propertySourceGroup, effectiveFlagGroupIndex, crossGroupPropsByKey, {
                allowAggregationRestore: sameIndexGroup !== undefined,
                incomingClearsAggregation: groupClearsAggregation || incomingClearsAggregation,
            })
        })
    }

    return result
}
