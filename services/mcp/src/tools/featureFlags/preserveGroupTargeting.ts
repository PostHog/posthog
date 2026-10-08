/**
 * Preserve group-based feature-flag targeting when MCP agents send partial `filters`.
 * Agents rebuild release conditions with only `key` / `operator` / `value`, and the API
 * reads an omitted property `type` as person, which silently converts a group flag to a
 * person flag (PostHog/posthog#46501).
 *
 * An incoming condition set takes the stored set at its own index as its source when every stored
 * set keeps its property keys at its index. New sets may only follow the stored ones. On a flag
 * whose stored sets aggregate on different group types, nothing else tells a moved set from an
 * edited one. The merge therefore refuses any other edit to such a flag, unless the payload changes
 * the flag-level aggregation or each set without a source states, clears, or implies its own: it
 * sends aggregation_group_type_index, carries an explicit person-aggregated property, or carries a
 * group property with a group_type_index. A set loses its source on such a flag when another stored
 * set on a different aggregation has the same keys and the incoming values differ from the stored
 * ones, because a swap of the two sets and an in-place edit of their values send the same payload.
 * On a flag whose sets all aggregate the same way, a set that keeps its keys at its index keeps its
 * source even when other sets change.
 *
 * A set's aggregation then decides its property types. A group-aggregated set restores a
 * person-aggregated type that its source holds for the key. It types every other untyped
 * property as `group` against the set's own group type index. A person-aggregated set restores
 * every stored type except `group`. check_property_types_match_aggregation in
 * products/feature_flags/backend/filters_validation.py reports a person-aggregated property in a
 * group set. The flag evaluator reads each property by its own type, so a group set keeps the
 * stored type of a person-aggregated property it holds.
 *
 * `aggregation_group_type_index: null` means person aggregation. Only a missing key is
 * filled from the existing flag.
 *
 * A condition set pinned to person aggregation never gains group targeting. A set is
 * pinned when it clears its own aggregation, when the payload changes the flag level to null, or
 * when it carries an explicit property of any type except `group` without setting a group index
 * itself.
 *
 * `super_groups` is ignored: the flags API drops it from writes
 * (LEGACY_UNKNOWN_FILTER_KEYS in products/feature_flags/backend/api/filters_schema.py).
 */

import { isDeepStrictEqual } from 'node:util'

import { ToolInputValidationError } from '@/lib/errors'
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

function hasExplicitPersonProperty(group: FlagConditionGroup): boolean {
    return Array.isArray(group.properties) && group.properties.some((p) => isPersonAggregatedType(p?.type))
}

/**
 * A set that carries its own group index is never pinned, which matches the backend's per-set
 * fallback in filters_validation.py. Any other set is pinned when it clears its own aggregation,
 * when the payload changes the flag level to null, or when it carries an explicit person-aggregated
 * property.
 */
function isPinnedToPerson(group: FlagConditionGroup, flagClearsAggregation: boolean): boolean {
    return (
        !isPresentGroupIndex(group.aggregation_group_type_index) &&
        (hasKey(group, 'aggregation_group_type_index') || flagClearsAggregation || hasExplicitPersonProperty(group))
    )
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

/**
 * Spans every existing set. A person-aggregated set takes a type from here when it has no source,
 * or when its source holds the key only as a group property.
 */
function indexPropertiesAcrossSets(existingSets: (ExistingSet | undefined)[]): Map<string, FlagProperty[]> {
    return indexProperties(
        existingSets.flatMap((existingSet) =>
            Array.isArray(existingSet?.group.properties) ? existingSet.group.properties : []
        )
    )
}

function hasSameKeySet(incoming: ReadonlyMap<string, unknown>, existing: ReadonlyMap<string, unknown>): boolean {
    return incoming.size === existing.size && [...incoming.keys()].every((key) => existing.has(key))
}

function soleItem<T>(items: T[]): T | undefined {
    return items.length === 1 ? items[0] : undefined
}

/** A set with no index of its own aggregates on the flag level, which the API distributes on write. */
function storedAggregation(group: FlagConditionGroup, flagLevelGroupIndex: number | undefined): number | null {
    if (isPresentGroupIndex(group.aggregation_group_type_index)) {
        return group.aggregation_group_type_index
    }
    return hasKey(group, 'aggregation_group_type_index') ? null : (flagLevelGroupIndex ?? null)
}

function keepsValues(incoming: FlagConditionGroup, source: ExistingSet): boolean {
    const properties = Array.isArray(incoming.properties) ? incoming.properties : []
    return properties.every(
        (prop) =>
            typeof prop?.key !== 'string' ||
            (source.propsByKey.get(prop.key) ?? []).some((stored) => isDeepStrictEqual(stored.value, prop.value))
    )
}

function keepsKeysAt(
    incomingGroups: FlagConditionGroup[],
    existingSets: (ExistingSet | undefined)[],
    index: number
): boolean {
    const incoming = incomingGroups[index]
    const incomingKeys = isRecord(incoming) ? indexProperties(incoming.properties) : new Map()
    return hasSameKeySet(incomingKeys, existingSets[index]?.propsByKey ?? new Map())
}

function keepsStoredSets(incomingGroups: FlagConditionGroup[], existingSets: (ExistingSet | undefined)[]): boolean {
    return (
        incomingGroups.length >= existingSets.length &&
        existingSets.every((_, index) => keepsKeysAt(incomingGroups, existingSets, index))
    )
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
    sourceCandidates: FlagProperty[] | undefined,
    otherCandidates: FlagProperty[] | undefined,
    setGroupTypeIndex: number | undefined
): FlagProperty {
    const out: FlagProperty = { ...incoming }

    if (!isPresentType(out.type)) {
        if (isPresentGroupIndex(setGroupTypeIndex)) {
            // A source that also holds the key as a group property leaves the type ambiguous.
            const sourceHoldsGroupProperty = sourceCandidates?.some((candidate) => candidate.type === 'group') ?? false
            const personType = sourceHoldsGroupProperty
                ? undefined
                : pickPersonAggregatedCandidate(sourceCandidates, out)?.type
            out.type = personType ?? 'group'
        } else {
            // Leaving the type unset makes the API report the property the agent actually
            // sent. Restoring `group` here would name fields the agent never sent.
            // A source set can lack the key, or hold it only as a group property that a person
            // set cannot use. The type then comes from another set that holds the key.
            const restored =
                pickPersonAggregatedCandidate(sourceCandidates, out) ??
                pickPersonAggregatedCandidate(otherCandidates, out)
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
    /** The payload changes the flag-level aggregation, which decides every set that sends none. */
    payloadChangesFlagAggregation: boolean
    /** This set never gains group targeting. See isPinnedToPerson. */
    pinnedToPerson: boolean
}

function explicitGroupPropertyIndex(group: FlagConditionGroup): number | undefined {
    const properties = Array.isArray(group.properties) ? group.properties : []
    const indexes = properties.flatMap((prop) =>
        prop?.type === 'group' && isPresentGroupIndex(prop.group_type_index) ? [prop.group_type_index] : []
    )
    return soleItem([...new Set(indexes)])
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
    if (hasExplicitPersonProperty(incoming) && !isPresentGroupIndex(out.aggregation_group_type_index)) {
        out.aggregation_group_type_index = null
    }

    const { pinnedToPerson, payloadChangesFlagAggregation } = options

    // Fill only when the key is absent. An explicit null means person aggregation. A payload
    // that changes the flag level already decides this set, the same way the API distributes
    // the flag level into every set that sends no index of its own. A group property that the
    // agent typed with an index names the group type of its own set. A retarget that the agent
    // sends only on the property therefore survives.
    if (!pinnedToPerson && !payloadChangesFlagAggregation && !hasKey(out, 'aggregation_group_type_index')) {
        const restored = explicitGroupPropertyIndex(incoming) ?? sourceSet?.group.aggregation_group_type_index
        if (isPresentGroupIndex(restored)) {
            out.aggregation_group_type_index = restored
        }
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
            return mergeProperty(
                prop,
                sourceSet?.propsByKey.get(prop.key),
                crossSetPropsByKey.get(prop.key),
                setGroupTypeIndex
            )
        })
    }

    return out
}

function unresolvedAggregationMessage(unresolved: number[]): string {
    const paths = unresolved.map((index) => `filters.groups[${index}]`).join(', ')
    return (
        "This flag's release conditions don't all target the same thing: some target persons and others a " +
        'group type, or they target different group types. This update adds, removes, or reorders conditions, ' +
        "or changes the properties they filter on, so the tool can't tell which target each condition should keep. " +
        `Set aggregation_group_type_index on each of these conditions: ${paths}. ` +
        'Use a group type index to target that group type, or null to target persons. Then send the update again.'
    )
}

/**
 * Merge incoming MCP filters with the flag's current filters. Explicitly set incoming
 * values always win, `null` included, and only missing `type`, `group_type_index`, and
 * `aggregation_group_type_index` keys are filled from the existing flag. The one exception
 * is a group property's `group_type_index`, which follows the index its own condition set
 * aggregates on. Any other index contradicts the set. The API reports that contradiction as
 * `group_property_type_index_mismatch`.
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

    // An echo of the stored flag level decides nothing new. validate_filters in
    // products/feature_flags/backend/api/feature_flag.py re-derives the stored flag level from the
    // condition sets on every write. It sets the flag level to null when the sets disagree. A
    // stored numeric flag level therefore equals the aggregation of every set the merge restores.
    const payloadChangesFlagAggregation =
        hasKey(incoming, 'aggregation_group_type_index') &&
        incoming.aggregation_group_type_index !== existing?.aggregation_group_type_index
    const incomingClearsAggregation = payloadChangesFlagAggregation && explicitlyClearsAggregation(incoming)

    // The flag-level index is the UI's "Target by" group type.
    if (!payloadChangesFlagAggregation && isPresentGroupIndex(existingFlagGroupIndex)) {
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
        const pinnedToPerson = result.groups.map(
            (group) => isRecord(group) && isPinnedToPerson(group, incomingClearsAggregation)
        )
        const aggregations = existingSets.map((existingSet) =>
            existingSet ? storedAggregation(existingSet.group, existingFlagGroupIndex) : undefined
        )
        const mixedAggregation = new Set(aggregations.filter((aggregation) => aggregation !== undefined)).size > 1
        const incomingGroups = result.groups
        const sharesKeysAcrossAggregations = (index: number): boolean =>
            existingSets.some(
                (other, otherIndex) =>
                    !!other &&
                    aggregations[otherIndex] !== aggregations[index] &&
                    hasSameKeySet(other.propsByKey, existingSets[index]?.propsByKey ?? new Map())
            )
        // On a single-aggregation flag a positional source cannot carry the wrong aggregation.
        const sourceSets = keepsStoredSets(incomingGroups, existingSets)
            ? existingSets.map((existingSet, index) => {
                  const group = incomingGroups[index]
                  const ambiguous =
                      mixedAggregation &&
                      !!existingSet &&
                      isRecord(group) &&
                      sharesKeysAcrossAggregations(index) &&
                      !keepsValues(group, existingSet)
                  return ambiguous ? undefined : existingSet
              })
            : mixedAggregation
              ? []
              : existingSets.map((existingSet, index) =>
                    keepsKeysAt(incomingGroups, existingSets, index) ? existingSet : undefined
                )

        if (mixedAggregation && !payloadChangesFlagAggregation) {
            const unresolved = result.groups.flatMap((group, index) =>
                isRecord(group) &&
                !sourceSets[index] &&
                !hasKey(group, 'aggregation_group_type_index') &&
                !pinnedToPerson[index] &&
                explicitGroupPropertyIndex(group) === undefined
                    ? [index]
                    : []
            )
            if (unresolved.length > 0) {
                throw new ToolInputValidationError(unresolvedAggregationMessage(unresolved), {
                    fields: ['filters.groups.N.aggregation_group_type_index:unresolved_aggregation'],
                })
            }
        }

        result.groups = result.groups.map((group, index) => {
            if (!isRecord(group)) {
                return group
            }

            return mergeConditionSet(group, sourceSets[index], effectiveFlagGroupIndex, crossSetPropsByKey, {
                payloadChangesFlagAggregation,
                pinnedToPerson: pinnedToPerson[index] ?? false,
            })
        })
    }

    return result
}
