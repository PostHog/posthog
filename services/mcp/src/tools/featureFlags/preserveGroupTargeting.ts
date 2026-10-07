/**
 * Preserve group-based feature-flag targeting when MCP agents send partial `filters`.
 * Agents rebuild release conditions with only `key` / `operator` / `value`, and the API
 * reads an omitted property `type` as person, which silently converts a group flag to a
 * person flag (PostHog/posthog#46501).
 *
 * Each incoming condition set is attributed to the existing set it came from. A set keeps the
 * existing set at its own index when the two share a property key. A moved set that shares a key
 * with the set now at its index therefore keeps that set as its source. Otherwise a set takes the
 * existing set that shares the most keys with it, when exactly one set does. A set with no key
 * match falls back to elimination, and then to position.
 *
 * A set's aggregation then decides its property types, in both directions. A group-aggregated
 * set types its untyped properties as `group` against the set's own group type index. A
 * person-aggregated set restores every stored type except `group`. Both rules, and the index a
 * group property carries, mirror check_property_types_match_aggregation in
 * products/feature_flags/backend/filters_validation.py.
 *
 * `aggregation_group_type_index: null` means person aggregation. Only a missing key is
 * filled from the existing flag.
 *
 * A condition set pinned to person aggregation never gains group targeting. A set is
 * pinned when the payload clears aggregation with an explicit null, or when it carries an
 * explicit property of any type except `group` without setting a group index itself.
 *
 * `super_groups` is ignored: the flags API drops it from writes
 * (LEGACY_UNKNOWN_FILTER_KEYS in products/feature_flags/backend/api/filters_schema.py).
 */

import { isRecord } from '@/lib/plain-object'

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

/**
 * `!== 'group'` is the complement of PERSON_AGGREGATED_PROPERTY_TYPES in filters_validation.py.
 * It holds only while 'group' is the sole type outside that tuple. A Python test asserts that:
 * products/feature_flags/backend/test/test_filters_validation.py. The complement also accepts a
 * stored type the backend tuples omit, such as `person_metadata`, which a hardcoded list drops.
 */
function isPersonAggregatedType(type: unknown): type is string {
    return isPresentType(type) && type !== 'group'
}

function hasKey(obj: Record<string, unknown> | null | undefined, key: string): boolean {
    return !!obj && Object.prototype.hasOwnProperty.call(obj, key)
}

function explicitlyClearsAggregation(obj: Record<string, unknown> | null | undefined): boolean {
    return hasKey(obj, 'aggregation_group_type_index') && !isPresentGroupIndex(obj?.aggregation_group_type_index)
}

function indexProperties(properties: FlagProperty[] | null | undefined): Map<string, FlagProperty[]> {
    const byKey = new Map<string, FlagProperty[]>()
    if (!Array.isArray(properties)) {
        return byKey
    }
    for (const prop of properties) {
        if (!prop || typeof prop.key !== 'string' || prop.key.length === 0) {
            continue
        }
        const list = byKey.get(prop.key) ?? []
        list.push(prop)
        byKey.set(prop.key, list)
    }
    return byKey
}

type ExistingSet = { group: FlagConditionGroup; propsByKey: Map<string, FlagProperty[]> }

function indexExistingSets(existing: FlagFilters | null | undefined): (ExistingSet | undefined)[] {
    const groups = existing?.groups
    if (!Array.isArray(groups)) {
        return []
    }
    return groups.map((group) =>
        isRecord(group) ? { group, propsByKey: indexProperties(group.properties) } : undefined
    )
}

/** Spans every existing set. The merge can then type a property after its own set is gone. */
function indexPropertiesAcrossSets(existingSets: (ExistingSet | undefined)[]): Map<string, FlagProperty[]> {
    return indexProperties(
        existingSets.flatMap((existingSet) =>
            Array.isArray(existingSet?.group.properties) ? existingSet.group.properties : []
        )
    )
}

function sharedKeyCount(incoming: ReadonlyMap<string, unknown>, existing: ReadonlyMap<string, unknown>): number {
    let shared = 0
    for (const key of incoming.keys()) {
        if (existing.has(key)) {
            shared++
        }
    }
    return shared
}

function soleItem<T>(items: T[]): T | undefined {
    return items.length === 1 ? items[0] : undefined
}

/**
 * Map each incoming condition set to the existing set it came from, by the property keys they
 * share. The set at the same index wins whenever it shares any key, even when another existing
 * set shares more. Otherwise the existing set that shares the most keys wins. The search tries the
 * existing sets that no incoming set has claimed first. It tries the claimed sets only when none
 * of the unclaimed sets match.
 */
function attributeSourceSets(
    incomingGroups: FlagConditionGroup[],
    existingSets: (ExistingSet | undefined)[]
): (ExistingSet | undefined)[] {
    const incoming = incomingGroups.map((group) => (isRecord(group) ? indexProperties(group.properties) : undefined))
    const sources: (ExistingSet | undefined)[] = incomingGroups.map(() => undefined)
    const claimed = new Set<number>()

    const claim = (index: number, existingIndex: number): void => {
        sources[index] = existingSets[existingIndex]
        claimed.add(existingIndex)
    }

    const claimSamePosition = ({ requireSharedKey }: { requireSharedKey: boolean }): void => {
        for (const [index, propsByKey] of incoming.entries()) {
            const candidate = existingSets[index]
            if (!propsByKey || sources[index] || !candidate || claimed.has(index)) {
                continue
            }
            if (!requireSharedKey || sharedKeyCount(propsByKey, candidate.propsByKey) > 0) {
                claim(index, index)
            }
        }
    }

    // A tie is not evidence of where the set came from. A tied set gets no match from this search.
    const uniqueBestMatch = (
        propsByKey: Map<string, FlagProperty[]>,
        { skipClaimed }: { skipClaimed: boolean }
    ): number => {
        let bestIndex = -1
        let bestShared = 0
        let tied = false
        for (const [existingIndex, candidate] of existingSets.entries()) {
            if (!candidate || (skipClaimed && claimed.has(existingIndex))) {
                continue
            }
            const shared = sharedKeyCount(propsByKey, candidate.propsByKey)
            if (shared === 0) {
                continue
            }
            if (shared > bestShared) {
                bestIndex = existingIndex
                bestShared = shared
                tied = false
            } else if (shared === bestShared) {
                tied = true
            }
        }
        return tied ? -1 : bestIndex
    }

    claimSamePosition({ requireSharedKey: true })

    for (const [index, propsByKey] of incoming.entries()) {
        if (!propsByKey || sources[index]) {
            continue
        }
        const unclaimedMatch = uniqueBestMatch(propsByKey, { skipClaimed: true })
        if (unclaimedMatch >= 0) {
            claim(index, unclaimedMatch)
            continue
        }
        // A set split off another set reads that set without claiming it. The split-off set then
        // has a source, and the elimination below does not pair it with an unrelated leftover set.
        const anyMatch = uniqueBestMatch(propsByKey, { skipClaimed: false })
        if (anyMatch >= 0) {
            sources[index] = existingSets[anyMatch]
        }
    }

    // A plain rollout has no property key to match. When exactly one incoming set and exactly one
    // existing set are left without a match, the two pair.
    const incomingIndex = soleItem(
        incoming.flatMap((propsByKey, index) => (propsByKey && !sources[index] ? [index] : []))
    )
    const existingIndex = soleItem(
        existingSets.flatMap((candidate, index) => (candidate && !claimed.has(index) ? [index] : []))
    )
    if (incomingIndex !== undefined && existingIndex !== undefined) {
        claim(incomingIndex, existingIndex)
    }

    claimSamePosition({ requireSharedKey: false })

    return sources
}

/** Callers fold an explicit null into `pinnedToPerson` first. `explicitIndex` cannot tell a
 * null from an absent key. */
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

function pickPersonAggregatedCandidate(
    candidates: FlagProperty[] | undefined,
    incoming: FlagProperty
): FlagProperty | undefined {
    const usable = (candidates ?? []).filter((candidate) => isPersonAggregatedType(candidate.type))
    if (incoming.operator) {
        const byOperator = usable.find((candidate) => candidate.operator === incoming.operator)
        if (byOperator) {
            return byOperator
        }
    }
    return usable[0]
}

function mergeProperty(
    incoming: FlagProperty,
    candidates: FlagProperty[] | undefined,
    setGroupTypeIndex: number | undefined
): FlagProperty {
    const out: FlagProperty = { ...incoming }

    if (!isPresentType(out.type)) {
        if (isPresentGroupIndex(setGroupTypeIndex)) {
            out.type = 'group'
        } else {
            // Leaving the type unset makes the API report the property the agent actually
            // sent. Restoring `group` here would name fields the agent never sent.
            const restored = pickPersonAggregatedCandidate(candidates, out)
            if (restored) {
                out.type = restored.type
            }
        }
    }

    // A group property carries the index its own set aggregates on. The set's index therefore
    // replaces an index the agent echoed back from the group type it retargets away from.
    if (out.type === 'group' && isPresentGroupIndex(setGroupTypeIndex)) {
        out.group_type_index = setGroupTypeIndex
    }

    return out
}

type MergeConditionOptions = {
    /** The payload states its own flag-level aggregation, which decides every set that sends none. */
    payloadStatesFlagAggregation: boolean
    /** This set resolves to person aggregation, by its own explicit null or by the flag level's null with no set index. */
    clearsAggregation: boolean
}

function mergeConditionSet(
    incoming: FlagConditionGroup,
    sourceSet: ExistingSet | undefined,
    flagLevelGroupIndex: number | undefined,
    crossSetPropsByKey: Map<string, FlagProperty[]>,
    options: MergeConditionOptions
): FlagConditionGroup {
    const out: FlagConditionGroup = { ...incoming }

    // One explicit property of a person-aggregated type stops this set from keeping or
    // gaining group targeting. An explicit incoming group index still wins. The API then
    // reports the contradiction in the agent's own payload.
    const hasExplicitNonGroupProperty =
        Array.isArray(incoming.properties) && incoming.properties.some((p) => isPersonAggregatedType(p?.type))
    const propertiesPinSetToPerson =
        hasExplicitNonGroupProperty && !isPresentGroupIndex(out.aggregation_group_type_index)
    if (propertiesPinSetToPerson) {
        out.aggregation_group_type_index = null
    }

    const pinnedToPerson = options.clearsAggregation || propertiesPinSetToPerson

    // Fill only when the key is absent. An explicit null means person aggregation. A payload
    // that states its own flag level already decides this set, the same way the API
    // distributes the flag level into every set that sends no index of its own. The merge also
    // skips the fill when the payload only echoes the stored flag level back. That is safe
    // because validate_filters in products/feature_flags/backend/api/feature_flag.py re-derives
    // the stored flag level from the condition sets on every write. It sets the flag level to
    // null when the sets disagree. A stored flag therefore never pairs a numeric flag level with
    // a set that aggregates on a different group type.
    if (
        !pinnedToPerson &&
        !options.payloadStatesFlagAggregation &&
        !hasKey(out, 'aggregation_group_type_index') &&
        sourceSet &&
        isPresentGroupIndex(sourceSet.group.aggregation_group_type_index)
    ) {
        out.aggregation_group_type_index = sourceSet.group.aggregation_group_type_index
    }

    const setGroupTypeIndex = resolveGroupIndex(pinnedToPerson, out.aggregation_group_type_index, flagLevelGroupIndex)

    if (Array.isArray(out.properties)) {
        out.properties = out.properties.map((prop) => {
            if (!prop || typeof prop !== 'object') {
                return prop
            }
            if (typeof prop.key !== 'string') {
                return prop
            }
            // A set with no source of its own can still name a property another set holds.
            const candidates = sourceSet?.propsByKey.get(prop.key) ?? crossSetPropsByKey.get(prop.key)
            return mergeProperty(prop, candidates, setGroupTypeIndex)
        })
    }

    return out
}

/**
 * Merge incoming MCP filters with the flag's current filters. Explicitly set incoming
 * values always win, `null` included, and only missing `type`, `group_type_index`, and
 * `aggregation_group_type_index` keys are filled from the existing flag. The one exception
 * is a group property's `group_type_index`, which follows the index its own condition set
 * aggregates on: any other index makes the API reject that property.
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
        ? existing.aggregation_group_type_index
        : undefined

    const payloadStatesFlagAggregation = hasKey(incoming, 'aggregation_group_type_index')
    const incomingClearsAggregation = explicitlyClearsAggregation(incoming)

    // The flag-level index is the UI's "Target by" group type.
    if (!payloadStatesFlagAggregation && isPresentGroupIndex(existingFlagGroupIndex)) {
        result.aggregation_group_type_index = existingFlagGroupIndex
    }

    const effectiveFlagGroupIndex = resolveGroupIndex(
        incomingClearsAggregation,
        result.aggregation_group_type_index,
        existingFlagGroupIndex
    )

    if (Array.isArray(result.groups)) {
        const existingSets = indexExistingSets(existing)
        const crossSetPropsByKey = indexPropertiesAcrossSets(existingSets)
        const sourceSets = attributeSourceSets(result.groups, existingSets)

        result.groups = result.groups.map((group, index) => {
            if (!isRecord(group)) {
                return group
            }

            return mergeConditionSet(group, sourceSets[index], effectiveFlagGroupIndex, crossSetPropsByKey, {
                payloadStatesFlagAggregation,
                // A flag-level clear only pins sets that omit the key. A set that carries its own
                // index keeps it, which matches the backend's per-set fallback in filters_validation.py.
                clearsAggregation:
                    explicitlyClearsAggregation(group) ||
                    (incomingClearsAggregation && !isPresentGroupIndex(group.aggregation_group_type_index)),
            })
        })
    }

    return result
}
