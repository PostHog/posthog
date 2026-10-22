/**
 * Preserve group-based feature-flag targeting when MCP agents send partial `filters`.
 * Agents rebuild release conditions with only `key` / `operator` / `value`. The API rejects a
 * property that has no `type`. A condition set without `aggregation_group_type_index` takes the
 * flag-level value, so it can lose its group targeting. The merge therefore restores these
 * omitted fields from the stored flag (PostHog/posthog#46501).
 *
 * The read tools add a `condition_id` to each condition set (see conditionIds.ts). When the payload
 * carries any condition_id, each set takes the stored set with the same ID as its source, at any
 * position. A set without an ID is then new. The merge refuses an ID that matches no stored set.
 * Such an ID usually means that the flag changed after the agent read it. A property whose key its
 * source does not hold takes its type from every stored set that holds the key. This also applies
 * on a flag whose stored sets aggregate on different group types. When that type does not fit the
 * set's aggregation, the API rejects the write. The rules below that pair sets by position and by
 * content apply only to a payload without IDs.
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
 * when the set states or implies its own group type. A group-aggregated set types a property as
 * `group` against its own group type index when the stored filters it reads hold the key as a group
 * property or hold no person-aggregated type for it. Otherwise the person-aggregated filters decide
 * the type.
 *
 * A person-aggregated set can filter on a group property. The flag evaluator reads each property
 * by its own type and group_type_index (see mixed_targeting_flag in
 * rust/feature-flags/src/flags/test_flag_matching.rs). A person-aggregated set therefore restores
 * `group` and the stored group_type_index from a source that is also stored as person-aggregated.
 * From a group-aggregated source, or from another stored set, it restores only person-aggregated
 * types. A set without a source can come from a stored set that holds the key as a group property.
 * When one does, the set restores a person-aggregated type only from a stored filter with the same
 * operator and value, and only when no group filter on the key also has them. Otherwise the property
 * stays untyped. A group property in a group-aggregated set says nothing about a person set. An echo of a
 * group property that a person-aggregated source holds does not move the set to group aggregation.
 * On a flag whose stored sets all aggregate on persons, a set without a source compares its echo
 * against every stored set instead. An appended set also has no source.
 * check_property_types_match_aggregation in products/feature_flags/backend/filters_validation.py
 * reports a group property in a person set and a person-aggregated property in a group set. The
 * evaluator supports both shapes. The merge keeps them where the stored flag already has them.
 *
 * In either kind of set, the stored filters that decide a type narrow to the ones that match the
 * incoming operator and value, then to the ones with its operator. When the rest hold more than one
 * typing, the property stays untyped. The API then rejects the write. A person-aggregated set with a
 * source reads other stored sets only when the source holds no filter on the key whose type it can
 * restore.
 *
 * An incoming person-aggregated set can keep the filters of other person-aggregated sets with the
 * same keys. The merge checks the incoming set's types against those sets only when the incoming set
 * changes the filters, rollout, or variant of its source, or when the payload does not keep them at
 * their own index, as after a deletion. A move
 * from any of those sets and an in-place edit that copies their filters send the same payload. The
 * edits can need different types, so the set restores a type only when typing the property from the
 * source and from each of those sets gives the same type and group_type_index. It looks up no other
 * stored set. A property that those stored sets type differently stays untyped, which makes the API
 * reject the write. When the source or one of those sets has every typed group property of the
 * incoming set on the same group type, those properties do not move the incoming set to group
 * aggregation.
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
import { canonicalJson, hasKey, isRecord } from '@/lib/plain-object'

import {
    explicitlyClearsAggregation,
    flagLevelGroupIndex,
    isPresentGroupIndex,
    resolveGroupIndex,
    storedAggregation,
} from './aggregation'
import { conditionId } from './conditionIds'

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

/**
 * `!== 'group'` is the complement of PERSON_AGGREGATED_PROPERTY_TYPES in filters_validation.py.
 * It holds only while 'group' is the sole type outside that tuple. A Python test asserts that:
 * products/feature_flags/backend/test/test_filters_validation.py. The complement also accepts a
 * stored type the backend tuples omit, such as `person_metadata`, which a hardcoded list drops.
 */
function isPersonAggregatedType(type: unknown): type is string {
    return isPresentType(type) && type !== 'group'
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

/** `aggregation` is null for a set that aggregates on persons. */
type ExistingSet = { group: FlagConditionGroup; propsByKey: Map<string, FlagProperty[]>; aggregation: number | null }

function indexExistingSets(
    existing: FlagFilters | null | undefined,
    flagLevel: number | undefined
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
                  aggregation: storedAggregation(group, flagLevel),
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

/** The flag evaluator ignores the value of an existence filter. */
const EXISTENCE_OPERATORS = new Set(['is_set', 'is_not_set'])

/** The flag evaluator reads a missing operator as `exact`. */
function evaluatedOperator(prop: FlagProperty): string {
    return prop.operator ?? 'exact'
}

/**
 * matchesFilter compares the same operator and value without building the pair. A filter that
 * matches another therefore always shares its signature.
 */
function evaluatedFilter(prop: FlagProperty): [operator: string, value: unknown] {
    const operator = evaluatedOperator(prop)
    return [operator, EXISTENCE_OPERATORS.has(operator) ? null : prop.value]
}

function matchesFilter(stored: FlagProperty, incoming: FlagProperty): boolean {
    const operator = evaluatedOperator(stored)
    return (
        operator === evaluatedOperator(incoming) &&
        (EXISTENCE_OPERATORS.has(operator) || isDeepStrictEqual(stored.value, incoming.value))
    )
}

/** A type or group_type_index that the agent sends and that differs from the stored filter is a change. */
function keepsExplicitTyping(stored: FlagProperty, incoming: FlagProperty): boolean {
    return (
        matchesFilter(stored, incoming) &&
        (!isPresentType(incoming.type) || incoming.type === stored.type) &&
        (!isPresentGroupIndex(incoming.group_type_index) || incoming.group_type_index === stored.group_type_index)
    )
}

/**
 * The filters under each key compare as a multiset of operator and value pairs, so a removed, added,
 * or changed filter on a key is a change.
 */
function keepsFilters(
    incoming: FlagConditionGroup,
    source: ExistingSet,
    matches: (stored: FlagProperty, incoming: FlagProperty) => boolean = matchesFilter
): boolean {
    const incomingByKey = indexProperties(incoming.properties)
    return (
        hasSameKeySet(incomingByKey, source.propsByKey) &&
        [...incomingByKey].every(([key, props]) => {
            const unmatched = [...(source.propsByKey.get(key) ?? [])]
            return (
                props.length === unmatched.length &&
                props.every((prop) => {
                    const match = unmatched.findIndex((stored) => matches(stored, prop))
                    if (match === -1) {
                        return false
                    }
                    unmatched.splice(match, 1)
                    return true
                })
            )
        })
    )
}

/** The values the flag evaluator reads for a missing or null field. */
const CONDITION_DEFAULTS = { rollout_percentage: 100, variant: null } as const

/**
 * An omitted field compares as the value the flag evaluator reads for it. The API replaces each
 * condition set whole. It does not keep the stored value of a field that the agent leaves out.
 */
function keepsCondition(incoming: FlagConditionGroup, source: ExistingSet): boolean {
    return (
        keepsFilters(incoming, source, keepsExplicitTyping) &&
        Object.entries(CONDITION_DEFAULTS).every(([field, fallback]) =>
            isDeepStrictEqual(incoming[field] ?? fallback, source.group[field] ?? fallback)
        )
    )
}

/** Sets that keepsFilters treats as having the same filters on the same keys share this signature. */
function filterSignature(propsByKey: Map<string, FlagProperty[]>): string {
    return JSON.stringify(
        [...propsByKey.values()]
            .flat()
            .map((prop) => canonicalJson([prop.key, ...evaluatedFilter(prop)]))
            .sort()
    )
}

/** Sets with this signature in common type every property the same way and hold the same group properties. */
function typingSignature(propsByKey: Map<string, FlagProperty[]>): string {
    return JSON.stringify(
        [...propsByKey.entries()]
            .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
            .map(([key, props]) => [
                key,
                props.map((prop) => [
                    prop.operator ?? null,
                    canonicalJson(prop.value),
                    prop.type ?? null,
                    prop.group_type_index ?? null,
                ]),
            ])
    )
}

/** `set` stands for every stored person set in `indexes`. */
type SameTypingSets = { set: ExistingSet; indexes: number[] }

/** A changed set compares against one stored set per typing instead of against every stored set. */
function groupPersonSetsByFilters(existingSets: (ExistingSet | undefined)[]): Map<string, SameTypingSets[]> {
    const byFilters = new Map<string, Map<string, SameTypingSets>>()
    existingSets.forEach((existingSet, index) => {
        if (!existingSet || existingSet.aggregation !== null) {
            return
        }
        const filters = filterSignature(existingSet.propsByKey)
        const byTyping = byFilters.get(filters) ?? new Map<string, SameTypingSets>()
        byFilters.set(filters, byTyping)
        const typing = typingSignature(existingSet.propsByKey)
        const sameTyping = byTyping.get(typing)
        if (sameTyping) {
            sameTyping.indexes.push(index)
        } else {
            byTyping.set(typing, { set: existingSet, indexes: [index] })
        }
    })
    return new Map([...byFilters].map(([filters, byTyping]) => [filters, [...byTyping.values()]]))
}

function keepsKeys(incoming: FlagConditionGroup | undefined, existingSet: ExistingSet | undefined): boolean {
    const incomingKeys = isRecord(incoming) ? indexProperties(incoming.properties) : new Map()
    return hasSameKeySet(incomingKeys, existingSet?.propsByKey ?? new Map())
}

function usableCandidates(
    candidates: FlagProperty[] | undefined,
    usableType: (type: unknown) => boolean
): FlagProperty[] {
    return (candidates ?? []).filter((candidate) => usableType(candidate.type))
}

function hasSameTypeAndGroupIndex(a: FlagProperty, b: FlagProperty): boolean {
    return a.type === b.type && (a.group_type_index ?? null) === (b.group_type_index ?? null)
}

function restoredTyping(stored: FlagProperty, incoming: FlagProperty): FlagProperty {
    return stored.type === 'group' && !isPresentGroupIndex(incoming.group_type_index)
        ? { type: stored.type, group_type_index: stored.group_type_index }
        : { type: stored.type }
}

/** Returning undefined when the typings disagree keeps the result independent of the order of the stored filters. */
function pickTyping(usable: FlagProperty[], incoming: FlagProperty): FlagProperty | undefined {
    const operator = evaluatedOperator(incoming)
    const matching = usable.filter((candidate) => matchesFilter(candidate, incoming))
    const sameOperator = usable.filter((candidate) => evaluatedOperator(candidate) === operator)
    const remaining = [matching, sameOperator, usable].find((tier) => tier.length > 0) ?? []
    const [first, ...rest] = remaining.map((candidate) => restoredTyping(candidate, incoming))
    return first && rest.every((typing) => hasSameTypeAndGroupIndex(typing, first)) ? first : undefined
}

function unambiguousPersonCandidates(
    candidates: FlagProperty[] | undefined,
    incoming: FlagProperty
): FlagProperty[] | undefined {
    if (!candidates?.some((candidate) => candidate.type === 'group')) {
        return candidates
    }
    const matching = candidates.filter((candidate) => matchesFilter(candidate, incoming))
    return matching.some((candidate) => candidate.type === 'group') ? [] : matching
}

type SourceAggregation = 'person' | 'group'

function mergeProperty(
    incoming: FlagProperty,
    candidates: FlagProperty[] | undefined,
    otherCandidates: FlagProperty[] | undefined,
    setGroupTypeIndex: number | undefined,
    source: SourceAggregation | undefined
): FlagProperty {
    const out: FlagProperty = { ...incoming }

    if (!isPresentType(out.type)) {
        if (isPresentGroupIndex(setGroupTypeIndex)) {
            const personTyped = usableCandidates(candidates, isPersonAggregatedType)
            // Candidates that also hold the key as a group property leave the type ambiguous.
            const restoredType =
                candidates?.some((candidate) => candidate.type === 'group') || personTyped.length === 0
                    ? 'group'
                    : pickTyping(personTyped, out)?.type
            if (restoredType) {
                out.type = restoredType
            }
        } else {
            // A person-aggregated source restores the group property it filters on, index
            // included. Any other candidate restores only a person-aggregated type, because
            // restoring `group` from it would name fields the agent never sent. Leaving the type
            // unset then makes the API report the property the agent actually sent.
            const fromSource = source
                ? usableCandidates(candidates, source === 'person' ? isPresentType : isPersonAggregatedType)
                : []
            const others = source ? otherCandidates : unambiguousPersonCandidates(otherCandidates, out)
            const usable = fromSource.length > 0 ? fromSource : usableCandidates(others, isPersonAggregatedType)
            const typing = pickTyping(usable, out)
            if (typing) {
                Object.assign(out, typing)
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
    sourceSet: ExistingSet | undefined,
    fallbackCandidatesByKey: Map<string, FlagProperty[]> | undefined,
    crossSetPropsByKey: Map<string, FlagProperty[]>,
    setGroupTypeIndex: number | undefined,
    matchedSets: ExistingSet[]
): FlagConditionGroup {
    const source: SourceAggregation | undefined = sourceSet && (sourceSet.aggregation === null ? 'person' : 'group')
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
            const candidates = sourceSet?.propsByKey.get(key)
            if (matchedSets.length === 0) {
                // A key the source does not hold takes its type from every stored set, even on a mixed flag.
                const sourceHoldsKey = candidates !== undefined
                return mergeProperty(
                    prop,
                    sourceHoldsKey ? candidates : fallbackCandidatesByKey?.get(key),
                    crossSetPropsByKey.get(key),
                    setGroupTypeIndex,
                    sourceHoldsKey ? source : undefined
                )
            }
            // The set either moved from one of the matched sets or copies its filters in place. Each
            // reading types the property from a different person set. Only a type that every reading
            // gives is safe.
            const fromSource = mergeProperty(prop, candidates, undefined, setGroupTypeIndex, 'person')
            const allAgree = matchedSets.every((matched) => {
                const fromMatched = mergeProperty(
                    prop,
                    matched.propsByKey.get(key),
                    undefined,
                    setGroupTypeIndex,
                    'person'
                )
                return hasSameTypeAndGroupIndex(fromMatched, fromSource)
            })
            return allAgree ? fromSource : prop
        })
    }

    return out
}

function groupPaths(indexes: number[]): string {
    return indexes.map((index) => `filters.groups[${index}]`).join(', ')
}

function unresolvedAggregationMessage(unresolved: number[]): string {
    const paths = groupPaths(unresolved)
    return (
        "This flag's release conditions don't all target the same thing: some target persons and others a " +
        'group type, or they target different group types. This update adds, removes, or reorders conditions, ' +
        "or changes the properties they filter on, so the tool can't tell which target each condition should keep. " +
        `Set aggregation_group_type_index on each of these conditions: ${paths}. ` +
        'Use a group type index to target that group type, or null to target persons. Then send the update again.'
    )
}

function staleConditionIdMessage(stale: number[]): string {
    const paths = groupPaths(stale)
    return (
        `The condition_id on ${paths} matches no condition on the flag. ` +
        'A condition_id only matches conditions on the flag you read it from. If you copied this condition ' +
        'from another flag or an experiment, remove its condition_id and send it as a new condition. ' +
        'Otherwise the flag may have changed after you read it. Read the flag again, then build the update ' +
        'from its current conditions and their condition_id values.'
    )
}

function sourcesByConditionId(
    conditionIds: (string | undefined)[],
    existingSets: (ExistingSet | undefined)[],
    existingFlagGroupIndex: number | undefined
): (ExistingSet | undefined)[] {
    const storedById = new Map<string, ExistingSet>()
    for (const existingSet of existingSets) {
        if (!existingSet) {
            continue
        }
        const id = conditionId(existingSet.group, existingFlagGroupIndex)
        if (!storedById.has(id)) {
            storedById.set(id, existingSet)
        }
    }
    const stale = conditionIds.flatMap((id, index) => (id !== undefined && !storedById.has(id) ? [index] : []))
    if (stale.length > 0) {
        throw new ToolInputValidationError(staleConditionIdMessage(stale), {
            fields: ['filters.groups.N.condition_id:stale_condition_id'],
        })
    }
    return conditionIds.map((id) => (id === undefined ? undefined : storedById.get(id)))
}

type SetSources = { sourceSets: (ExistingSet | undefined)[]; matchedPersonSets: ExistingSet[][] }

function matchSetsByPositionAndContent(
    incomingGroups: FlagConditionGroup[],
    existingSets: (ExistingSet | undefined)[],
    mixedAggregation: boolean
): SetSources {
    const keptKeys = existingSets.map((existingSet, index) => keepsKeys(incomingGroups[index], existingSet))
    // On a single-aggregation flag a positional source cannot carry the wrong aggregation.
    const positionHolds = !mixedAggregation || (incomingGroups.length >= existingSets.length && keptKeys.every(Boolean))
    const sourceSets = incomingGroups.map((group, index) => {
        const existingSet = existingSets[index]
        const ambiguous =
            mixedAggregation &&
            !!existingSet &&
            isRecord(group) &&
            existingSets.some(
                (other) =>
                    !!other &&
                    other.aggregation !== existingSet.aggregation &&
                    hasSameKeySet(other.propsByKey, existingSet.propsByKey)
            ) &&
            !keepsFilters(group, existingSet)
        return positionHolds && keptKeys[index] && !ambiguous ? existingSet : undefined
    })
    const keptConditions = existingSets.map((existingSet, index) => {
        const group = incomingGroups[index]
        return !!existingSet && isRecord(group) && keepsCondition(group, existingSet)
    })
    const personSetsByFilters = groupPersonSetsByFilters(existingSets)
    const changedTypings = new Set(
        [...personSetsByFilters.values()]
            .flat()
            .filter((sameTyping) => sameTyping.indexes.some((otherIndex) => !keptConditions[otherIndex]))
    )
    const matchedPersonSets = sourceSets.map((sourceSet, index) => {
        const group = incomingGroups[index]
        if (sourceSet?.aggregation !== null || !isRecord(group)) {
            return []
        }
        return (personSetsByFilters.get(filterSignature(indexProperties(group.properties))) ?? [])
            .filter(
                (sameTyping) =>
                    sameTyping.indexes.some((otherIndex) => otherIndex !== index) &&
                    keepsFilters(group, sameTyping.set) &&
                    (!keptConditions[index] || changedTypings.has(sameTyping))
            )
            .map((sameTyping) => sameTyping.set)
    })
    return { sourceSets, matchedPersonSets }
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

    const existingFlagGroupIndex = flagLevelGroupIndex(existing)

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
        const conditionIds = result.groups.map((group) =>
            isRecord(group) && typeof group.condition_id === 'string' ? group.condition_id : undefined
        )
        result.groups = result.groups.map((group) => {
            if (!isRecord(group)) {
                return group
            }
            const { condition_id: _conditionId, ...rest } = group
            return rest
        })
        const carriesConditionIds = conditionIds.some((id) => id !== undefined)
        const pinnedToPerson = result.groups.map(
            (group) => isRecord(group) && isPinnedToPerson(group, incomingClearsAggregation)
        )
        const aggregations = existingSets.map((existingSet) => existingSet?.aggregation)
        const storedAggregations = new Set(aggregations.filter((aggregation) => aggregation !== undefined))
        const mixedAggregation = storedAggregations.size > 1
        const aggregatesOnPersonsOnly = storedAggregations.size === 1 && storedAggregations.has(null)
        const { sourceSets, matchedPersonSets }: SetSources = carriesConditionIds
            ? {
                  sourceSets: sourcesByConditionId(conditionIds, existingSets, existingFlagGroupIndex),
                  matchedPersonSets: [],
              }
            : matchSetsByPositionAndContent(result.groups, existingSets, mixedAggregation)
        const personSources = sourceSets.map((sourceSet) => (sourceSet?.aggregation === null ? sourceSet : undefined))

        const personSetPropsFor = (index: number): (Map<string, FlagProperty[]> | undefined)[] =>
            sourceSets[index]
                ? [personSources[index], ...(matchedPersonSets[index] ?? [])].map((personSet) => personSet?.propsByKey)
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
            const fallbackCandidatesByKey =
                !mixedAggregation || statesOwnGroupType[index] || sourceSets[index] ? crossSetPropsByKey : undefined
            return typeSetProperties(
                group,
                sourceSets[index],
                fallbackCandidatesByKey,
                crossSetPropsByKey,
                resolveGroupIndex(
                    pinnedToPerson[index] ?? false,
                    group.aggregation_group_type_index,
                    effectiveFlagGroupIndex
                ),
                matchedPersonSets[index] ?? []
            )
        })
    }

    return result
}
