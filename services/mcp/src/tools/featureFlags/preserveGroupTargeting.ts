/**
 * Preserve group-based feature-flag targeting when MCP agents send partial `filters`.
 * Agents rebuild release conditions with only `key` / `operator` / `value`. The API rejects a
 * property that has no `type`. A condition set without `aggregation_group_type_index` takes the
 * flag-level value, so it can lose its group targeting. The merge therefore restores these
 * omitted fields from the stored flag (PostHog/posthog#46501).
 *
 * An incoming condition set takes the stored set at its own index as its source when every stored
 * set keeps its property keys at its index. New sets may only follow the stored ones. On a flag
 * whose stored sets aggregate on different group types, nothing else tells a moved set from an
 * edited one. The merge therefore refuses any other edit to such a flag, unless the payload changes
 * the flag-level aggregation or each set without a source states, clears, or implies its own: it
 * sends aggregation_group_type_index, carries an explicit person-aggregated property, or carries a
 * group property with a group_type_index. A set loses its source on such a flag when another stored
 * set on a different aggregation has the same keys and the incoming operators or values differ from
 * the stored ones, because a swap of the two sets and an in-place edit of their filters send the
 * same payload. On a flag whose sets all aggregate the same way, a set that keeps its keys at its
 * index keeps its source even when other sets change.
 *
 * A set's aggregation then decides its property types. A group-aggregated set restores a
 * person-aggregated type that its source holds for the key. A group-aggregated set with no source
 * looks the key up in every stored set instead when the stored sets all aggregate the same way, or
 * when the set states or implies its own group type. It types every other untyped property as
 * `group` against the set's own group type index.
 *
 * A person-aggregated set can filter on a group property. The flag evaluator reads each property
 * by its own type and group_type_index (see mixed_targeting_flag in
 * rust/feature-flags/src/flags/test_flag_matching.rs). A person-aggregated set therefore restores
 * `group` and the stored group_type_index from a source that is also stored as person-aggregated.
 * From a group-aggregated source, or from another stored set, it restores only person-aggregated
 * types. A group property in a group-aggregated set says nothing about a person set. An echo of a
 * group property that a person-aggregated source holds does not move the set to group aggregation.
 * On a flag whose stored sets all aggregate on persons, a set without a source compares its echo
 * against every stored set instead. An appended set also has no source.
 * check_property_types_match_aggregation in products/feature_flags/backend/filters_validation.py
 * reports a group property in a person set and a person-aggregated property in a group set. The
 * evaluator supports both shapes. The merge keeps them where the stored flag already has them.
 *
 * An incoming person-aggregated set can keep the filters of other person-aggregated sets with the
 * same keys. Those sets count when the incoming set changes the filters, rollout, or variant of its
 * source, or when the payload does not keep them at their own index, as after a deletion. A move
 * from any of those sets and an in-place edit that copies their filters send the same payload. The
 * edits can need different types, so the set restores a type only when typing the property from the
 * source and from each of those sets gives the same type and group_type_index. It looks up no other
 * stored set. A property that those stored sets type differently stays untyped, which makes the API
 * reject the write. When the source or one stored person-aggregated set whose filters the incoming
 * set keeps has every typed group property of the incoming set on the same group type, those
 * properties do not move the incoming set to group aggregation. That check counts such a set even when
 * both sets keep their own condition, because a typed swap of two sets with the same filters keeps
 * both conditions.
 *
 * `aggregation_group_type_index: null` means person aggregation. Only a missing key is
 * filled from the existing flag.
 *
 * A condition set pinned to person aggregation never gains group aggregation. A set is
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

/** A set with no index of its own aggregates on the flag level, which the API distributes on write. */
function storedAggregation(group: FlagConditionGroup, flagLevelGroupIndex: number | undefined): number | null {
    return (
        resolveGroupIndex(
            explicitlyClearsAggregation(group),
            group.aggregation_group_type_index,
            flagLevelGroupIndex
        ) ?? null
    )
}

/** `aggregation` is null for a set that aggregates on persons. */
type ExistingSet = { group: FlagConditionGroup; propsByKey: Map<string, FlagProperty[]>; aggregation: number | null }

function indexExistingSets(
    existing: FlagFilters | null | undefined,
    flagLevelGroupIndex: number | undefined
): (ExistingSet | undefined)[] {
    const groups = existing?.groups
    if (!Array.isArray(groups)) {
        return []
    }
    return groups.map((group) =>
        isRecord(group)
            ? {
                  group,
                  propsByKey: indexProperties(group.properties),
                  aggregation: storedAggregation(group, flagLevelGroupIndex),
              }
            : undefined
    )
}

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

/** The flag evaluator reads a missing operator as `exact`. */
function matchesFilter(stored: FlagProperty, incoming: FlagProperty): boolean {
    return (
        (stored.operator ?? 'exact') === (incoming.operator ?? 'exact') &&
        isDeepStrictEqual(stored.value, incoming.value)
    )
}

/**
 * The filters under each key compare as a multiset of operator and value pairs, so a removed, added,
 * or changed filter on a key is a change.
 */
function keepsFilters(incoming: FlagConditionGroup, source: ExistingSet): boolean {
    return [...indexProperties(incoming.properties)].every(([key, props]) => {
        const unmatched = [...(source.propsByKey.get(key) ?? [])]
        return (
            props.length === unmatched.length &&
            props.every((prop) => {
                const match = unmatched.findIndex((stored) => matchesFilter(stored, prop))
                if (match === -1) {
                    return false
                }
                unmatched.splice(match, 1)
                return true
            })
        )
    })
}

/** A field that the agent omits is not a change, so an echo that leaves it out still keeps its source. */
function keepsCondition(incoming: FlagConditionGroup, source: ExistingSet): boolean {
    return (
        keepsFilters(incoming, source) &&
        (['rollout_percentage', 'variant'] as const).every(
            (field) => !hasKey(incoming, field) || isDeepStrictEqual(incoming[field], source.group[field])
        )
    )
}

function keepsKeys(incoming: FlagConditionGroup | undefined, existingSet: ExistingSet | undefined): boolean {
    const incomingKeys = isRecord(incoming) ? indexProperties(incoming.properties) : new Map()
    return hasSameKeySet(incomingKeys, existingSet?.propsByKey ?? new Map())
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

function pickCandidate(
    candidates: FlagProperty[] | undefined,
    incoming: FlagProperty,
    usableType: (type: unknown) => boolean
): FlagProperty | undefined {
    const usable = (candidates ?? []).filter((candidate) => usableType(candidate.type))
    // Two group filters on one key can share an operator and differ only in group type and value.
    return (
        usable.find((candidate) => matchesFilter(candidate, incoming)) ??
        (incoming.operator ? usable.find((candidate) => candidate.operator === incoming.operator) : undefined) ??
        usable[0]
    )
}

function mergeProperty(
    incoming: FlagProperty,
    candidates: FlagProperty[] | undefined,
    otherCandidates: FlagProperty[] | undefined,
    setGroupTypeIndex: number | undefined,
    sourceRestoresGroupType: boolean
): FlagProperty {
    const out: FlagProperty = { ...incoming }

    if (!isPresentType(out.type)) {
        if (isPresentGroupIndex(setGroupTypeIndex)) {
            // Candidates that also hold the key as a group property leave the type ambiguous.
            out.type = candidates?.some((candidate) => candidate.type === 'group')
                ? 'group'
                : (pickCandidate(candidates, out, isPersonAggregatedType)?.type ?? 'group')
        } else {
            // A person-aggregated source restores the group property it filters on, index
            // included, unless the set keeps the filters of another person set instead. Any other
            // candidate restores only a person-aggregated type, because restoring `group` from it
            // would name fields the agent never sent. Leaving the type unset then makes the API
            // report the property the agent actually sent.
            const restored =
                pickCandidate(candidates, out, sourceRestoresGroupType ? isPresentType : isPersonAggregatedType) ??
                pickCandidate(otherCandidates, out, isPersonAggregatedType)
            if (restored) {
                out.type = restored.type
                if (restored.type === 'group' && !isPresentGroupIndex(out.group_type_index)) {
                    out.group_type_index = restored.group_type_index
                }
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
    /** This set never gains group aggregation. See isPinnedToPerson. */
    pinnedToPerson: boolean
    /** Property maps of the stored person sets that this set may come from. */
    personSetProps: (Map<string, FlagProperty[]> | undefined)[]
}

function holdsGroupProperty(propsByKey: Map<string, FlagProperty[]> | undefined, prop: FlagProperty): boolean {
    return (
        typeof prop.key === 'string' &&
        !!propsByKey
            ?.get(prop.key)
            ?.some((stored) => stored.type === 'group' && stored.group_type_index === prop.group_type_index)
    )
}

function explicitGroupPropertyIndex(
    group: FlagConditionGroup,
    personSetProps: (Map<string, FlagProperty[]> | undefined)[]
): number | undefined {
    const properties = Array.isArray(group.properties) ? group.properties : []
    const typed = properties.filter(
        (prop): prop is FlagProperty & { group_type_index: number } =>
            prop?.type === 'group' && isPresentGroupIndex(prop.group_type_index)
    )
    if (personSetProps.some((propsByKey) => typed.every((prop) => holdsGroupProperty(propsByKey, prop)))) {
        return undefined
    }
    const unique = [...new Set(typed.map((prop) => prop.group_type_index))]
    return unique.length === 1 ? unique[0] : undefined
}

function resolveSetAggregation(
    incoming: FlagConditionGroup,
    sourceSet: ExistingSet | undefined,
    options: MergeConditionOptions
): FlagConditionGroup {
    const out: FlagConditionGroup = { ...incoming }

    // One explicit property of a person-aggregated type stops this set from keeping or
    // gaining group targeting. An explicit incoming group index still wins. The API then
    // reports the contradiction in the agent's own payload.
    if (hasExplicitPersonProperty(incoming) && !isPresentGroupIndex(out.aggregation_group_type_index)) {
        out.aggregation_group_type_index = null
    }

    const { pinnedToPerson, payloadChangesFlagAggregation, personSetProps } = options

    // Fill only when the key is absent. An explicit null means person aggregation. A payload
    // that changes the flag level already decides this set, the same way the API distributes
    // the flag level into every set that sends no index of its own. A group property that the
    // agent typed with an index names the group type of its own set. A retarget that the agent
    // sends only on the property therefore survives. A set whose typed group properties all
    // repeat ones that a single map in personSetProps holds names no group type, because the
    // stored person-aggregated set filters on them without aggregating on their group type.
    if (!pinnedToPerson && !payloadChangesFlagAggregation && !hasKey(out, 'aggregation_group_type_index')) {
        const restored =
            explicitGroupPropertyIndex(incoming, personSetProps) ?? sourceSet?.group.aggregation_group_type_index
        if (isPresentGroupIndex(restored)) {
            out.aggregation_group_type_index = restored
        }
    }

    return out
}

function typeSetProperties(
    group: FlagConditionGroup,
    typeCandidatesByKey: Map<string, FlagProperty[]> | undefined,
    crossSetPropsByKey: Map<string, FlagProperty[]>,
    setGroupTypeIndex: number | undefined,
    sourceAggregatesOnPersons: boolean,
    matchedSets: ExistingSet[]
): FlagConditionGroup {
    const out: FlagConditionGroup = { ...group }
    if (Array.isArray(out.properties)) {
        out.properties = out.properties.map((prop) => {
            if (!prop || typeof prop !== 'object') {
                return prop
            }
            const key = prop.key
            if (typeof key !== 'string') {
                return prop
            }
            const candidates = typeCandidatesByKey?.get(key)
            if (matchedSets.length === 0) {
                return mergeProperty(
                    prop,
                    candidates,
                    crossSetPropsByKey.get(key),
                    setGroupTypeIndex,
                    sourceAggregatesOnPersons
                )
            }
            // The set either moved from one of the matched sets or copies its filters in place. Each
            // reading types the property from a different person set. Only a type that every reading
            // gives is safe.
            const fromSource = mergeProperty(prop, candidates, undefined, setGroupTypeIndex, true)
            const allAgree = matchedSets.every((matched) => {
                const fromMatched = mergeProperty(prop, matched.propsByKey.get(key), undefined, setGroupTypeIndex, true)
                return (
                    fromMatched.type === fromSource.type && fromMatched.group_type_index === fromSource.group_type_index
                )
            })
            return allAgree ? fromSource : prop
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
        const existingSets = indexExistingSets(existing, existingFlagGroupIndex)
        const crossSetPropsByKey = indexPropertiesAcrossSets(existingSets)
        const pinnedToPerson = result.groups.map(
            (group) => isRecord(group) && isPinnedToPerson(group, incomingClearsAggregation)
        )
        const aggregations = existingSets.map((existingSet) => existingSet?.aggregation)
        const storedAggregations = new Set(aggregations.filter((aggregation) => aggregation !== undefined))
        const mixedAggregation = storedAggregations.size > 1
        const aggregatesOnPersonsOnly = storedAggregations.size === 1 && storedAggregations.has(null)
        const incomingGroups = result.groups
        const sameKeySets = (existingSet: ExistingSet): ExistingSet[] =>
            existingSets.filter(
                (other): other is ExistingSet => !!other && hasSameKeySet(other.propsByKey, existingSet.propsByKey)
            )
        const keptKeys = existingSets.map((existingSet, index) => keepsKeys(incomingGroups[index], existingSet))
        // On a single-aggregation flag a positional source cannot carry the wrong aggregation.
        const positionHolds =
            !mixedAggregation || (incomingGroups.length >= existingSets.length && keptKeys.every(Boolean))
        const sourceSets = existingSets.map((existingSet, index) => {
            const group = incomingGroups[index]
            const ambiguous =
                mixedAggregation &&
                !!existingSet &&
                isRecord(group) &&
                sameKeySets(existingSet).some((other) => other.aggregation !== existingSet.aggregation) &&
                !keepsFilters(group, existingSet)
            return positionHolds && keptKeys[index] && !ambiguous ? existingSet : undefined
        })
        const personSources = sourceSets.map((sourceSet) => (sourceSet?.aggregation === null ? sourceSet : undefined))
        const keptConditions = existingSets.map((existingSet, index) => {
            const group = incomingGroups[index]
            return !!existingSet && isRecord(group) && keepsCondition(group, existingSet)
        })
        const sameFilterPersonSets = personSources.map((personSource, index) => {
            const group = incomingGroups[index]
            if (!personSource || !isRecord(group)) {
                return []
            }
            return existingSets.flatMap((other, otherIndex) =>
                other &&
                otherIndex !== index &&
                other.aggregation === null &&
                hasSameKeySet(other.propsByKey, personSource.propsByKey) &&
                keepsFilters(group, other)
                    ? [{ set: other, index: otherIndex }]
                    : []
            )
        })
        const matchedPersonSets = sameFilterPersonSets.map((matches, index) =>
            matches.filter((match) => !keptConditions[index] || !keptConditions[match.index]).map((match) => match.set)
        )

        const personSetPropsFor = (index: number): (Map<string, FlagProperty[]> | undefined)[] =>
            sourceSets[index]
                ? [personSources[index], ...(sameFilterPersonSets[index] ?? []).map((match) => match.set)].map(
                      (personSet) => personSet?.propsByKey
                  )
                : [aggregatesOnPersonsOnly ? crossSetPropsByKey : undefined]

        const resolvedGroups = result.groups.map((group, index) =>
            isRecord(group)
                ? resolveSetAggregation(group, sourceSets[index], {
                      payloadChangesFlagAggregation,
                      pinnedToPerson: pinnedToPerson[index] ?? false,
                      personSetProps: personSetPropsFor(index),
                  })
                : group
        )
        const statesOwnGroupType = resolvedGroups.map(
            (group) => isRecord(group) && isPresentGroupIndex(group.aggregation_group_type_index)
        )

        if (mixedAggregation && !payloadChangesFlagAggregation) {
            const unresolved = resolvedGroups.flatMap((group, index) =>
                isRecord(group) && !sourceSets[index] && !pinnedToPerson[index] && !statesOwnGroupType[index]
                    ? [index]
                    : []
            )
            if (unresolved.length > 0) {
                throw new ToolInputValidationError(unresolvedAggregationMessage(unresolved), {
                    fields: ['filters.groups.N.aggregation_group_type_index:unresolved_aggregation'],
                })
            }
        }

        result.groups = resolvedGroups.map((group, index) => {
            if (!isRecord(group)) {
                return group
            }
            const typeCandidatesByKey =
                sourceSets[index]?.propsByKey ??
                (!mixedAggregation || statesOwnGroupType[index] ? crossSetPropsByKey : undefined)
            return typeSetProperties(
                group,
                typeCandidatesByKey,
                crossSetPropsByKey,
                resolveGroupIndex(
                    pinnedToPerson[index] ?? false,
                    group.aggregation_group_type_index,
                    effectiveFlagGroupIndex
                ),
                !!personSources[index],
                matchedPersonSets[index] ?? []
            )
        })
    }

    return result
}
