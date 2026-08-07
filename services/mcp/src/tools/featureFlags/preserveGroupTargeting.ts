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
 * Note on `super_groups`: the backend also stores `filters.super_groups[]` for
 * legacy multi-condition evaluation. Group-targeted flags used by MCP agents
 * today put group aggregation on `filters.groups` / flag-level
 * `aggregation_group_type_index`. We do not rewrite `super_groups` here; if a
 * future product path stores group properties only under `super_groups`, extend
 * this helper to walk that array the same way as `groups`.
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
    /** See file header — not rewritten by preserveGroupTargetingFilters today. */
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

function pickMatchingExisting(candidates: FlagProperty[] | undefined, incoming: FlagProperty): FlagProperty | undefined {
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

function mergeProperty(
    incoming: FlagProperty,
    existingProp: FlagProperty | undefined,
    fallbackGroupTypeIndex: number | undefined
): FlagProperty {
    const out: FlagProperty = { ...incoming }

    if (!isPresentType(out.type) && existingProp && isPresentType(existingProp.type)) {
        out.type = existingProp.type
    }

    // If this condition set is group-aggregated and type is still missing, prefer group.
    if (!isPresentType(out.type) && isPresentGroupIndex(fallbackGroupTypeIndex)) {
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

function mergeConditionGroup(
    incoming: FlagConditionGroup,
    existingGroup: FlagConditionGroup | undefined,
    flagLevelGroupIndex: number | undefined,
    crossGroupPropsByKey: Map<string, FlagProperty[]>
): FlagConditionGroup {
    const out: FlagConditionGroup = { ...incoming }

    // Prefer explicit incoming aggregation; else keep group-level aggregation from existing.
    if (!isPresentGroupIndex(out.aggregation_group_type_index)) {
        if (existingGroup && isPresentGroupIndex(existingGroup.aggregation_group_type_index)) {
            out.aggregation_group_type_index = existingGroup.aggregation_group_type_index
        }
    }

    const effectiveGroupIndex = isPresentGroupIndex(out.aggregation_group_type_index)
        ? out.aggregation_group_type_index
        : flagLevelGroupIndex

    if (Array.isArray(out.properties)) {
        const sameGroupByKey = new Map<string, FlagProperty[]>()
        if (Array.isArray(existingGroup?.properties)) {
            for (const p of existingGroup.properties) {
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
            return mergeProperty(prop, existingProp, effectiveGroupIndex)
        })
    }

    return out
}

/**
 * Merge incoming MCP filters with the flag's current filters so group targeting
 * is not silently demoted to person targeting.
 *
 * Incoming values always win when explicitly set. Only *missing* type /
 * group_type_index / aggregation_group_type_index fields are filled from existing.
 */
export function preserveGroupTargetingFilters(
    existing: FlagFilters | null | undefined,
    incoming: FlagFilters | null | undefined
): FlagFilters {
    if (!incoming || typeof incoming !== 'object') {
        return incoming as FlagFilters
    }

    const result: FlagFilters = { ...incoming }

    const existingFlagGroupIndex = isPresentGroupIndex(existing?.aggregation_group_type_index)
        ? existing!.aggregation_group_type_index!
        : undefined

    // Preserve flag-level group aggregation (UI "Target by" group type).
    if (!isPresentGroupIndex(result.aggregation_group_type_index) && isPresentGroupIndex(existingFlagGroupIndex)) {
        result.aggregation_group_type_index = existingFlagGroupIndex
    }

    const effectiveFlagGroupIndex = isPresentGroupIndex(result.aggregation_group_type_index)
        ? result.aggregation_group_type_index!
        : existingFlagGroupIndex

    const crossGroupPropsByKey = indexExistingProperties(existing)

    if (Array.isArray(result.groups)) {
        const existingGroups = Array.isArray(existing?.groups) ? existing!.groups! : []
        result.groups = result.groups.map((group, index) => {
            if (!group || typeof group !== 'object') {
                return group
            }
            // Prefer same-index group, then any existing group with group aggregation.
            const existingGroup =
                existingGroups[index] ??
                existingGroups.find((g) => isPresentGroupIndex(g?.aggregation_group_type_index)) ??
                existingGroups[0]

            return mergeConditionGroup(group, existingGroup, effectiveFlagGroupIndex, crossGroupPropsByKey)
        })
    }

    return result
}
