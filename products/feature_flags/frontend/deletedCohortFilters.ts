import { COHORT_ANNOTATION_KEYS, isCohortPropertyFilter } from 'lib/components/PropertyFilters/utils'

import {
    AnyPropertyFilter,
    CohortPropertyFilter,
    FeatureFlagConfig,
    FeatureFlagFilters,
    FeatureFlagType,
} from '~/types'

import { isV1FeatureFlagConfig } from './featureFlagConfigFormat'

/** Whether a condition's deleted cohort still exists, so that its page can restore it. */
export function cohortCanBeRestored(property: CohortPropertyFilter): boolean {
    return !property.cohort_missing
}

/**
 * Whether restoring the flag runs the flag API's cohort check.
 * A restore that leaves the flag archived skips the check, because unarchiving the flag runs it.
 */
export function restoreChecksCohorts(flag: Pick<FeatureFlagType, 'deleted' | 'archived'>): boolean {
    return !!flag.deleted && !flag.archived
}

/**
 * Why a control that enables, unarchives or restores the flag is disabled, given the flag's `deletedCohortFilters`.
 * The flag API refuses those writes while a release condition targets a deleted cohort.
 * Returns undefined when `conditions` is empty, so the control stays enabled.
 */
export function deletedCohortDisabledReason(conditions: CohortPropertyFilter[]): string | undefined {
    if (conditions.length === 0) {
        return undefined
    }
    const theCohorts = conditions.length === 1 ? 'the cohort' : 'the cohorts'
    return conditions.every(cohortCanBeRestored)
        ? `A release condition targets a deleted cohort. Restore ${theCohorts} or update the release conditions first.`
        : 'A release condition targets a cohort that does not exist in this project. Update the release conditions first.'
}

/**
 * The properties in a v1 config's release conditions.
 * It skips a group whose `properties` is not a list, as the flag API does.
 * One malformed flag therefore cannot break the flag list, which reads every flag.
 */
function releaseConditionProperties(filters: FeatureFlagFilters): (AnyPropertyFilter | null)[] {
    const groups: unknown = filters.groups
    if (!Array.isArray(groups)) {
        return []
    }
    return groups.flatMap((group) => (Array.isArray(group?.properties) ? group.properties : []))
}

/** The release conditions that target a deleted or missing cohort, one per cohort. */
export function deletedCohortFilters(filters: FeatureFlagConfig | null | undefined): CohortPropertyFilter[] {
    if (!filters || !isV1FeatureFlagConfig(filters)) {
        return []
    }
    // Stored cohort values can be numbers or numeric strings. `5` and `"5"` name the same cohort.
    const byCohort = new Map<string, CohortPropertyFilter>()
    for (const property of releaseConditionProperties(filters)) {
        if (isCohortPropertyFilter(property) && property.cohort_deleted && !byCohort.has(String(property.value))) {
            byCohort.set(String(property.value), property)
        }
    }
    return [...byCohort.values()]
}

/** Copies `source`'s cohort annotations onto `flag`'s cohort conditions that name the same cohort. */
export function withCohortAnnotationsFrom(flag: FeatureFlagType, source: FeatureFlagType): FeatureFlagType {
    if (!isV1FeatureFlagConfig(flag.filters) || !isV1FeatureFlagConfig(source.filters)) {
        return flag
    }
    const annotatedByCohort = new Map<string, CohortPropertyFilter>()
    for (const property of releaseConditionProperties(source.filters)) {
        if (isCohortPropertyFilter(property)) {
            annotatedByCohort.set(String(property.value), property)
        }
    }
    const reannotate = (property: AnyPropertyFilter): AnyPropertyFilter => {
        const annotated = isCohortPropertyFilter(property) ? annotatedByCohort.get(String(property.value)) : undefined
        if (!annotated) {
            return property
        }
        const updated: Record<string, unknown> = { ...property }
        for (const key of COHORT_ANNOTATION_KEYS) {
            if (annotated[key] === undefined) {
                delete updated[key]
            } else {
                updated[key] = annotated[key]
            }
        }
        return updated as AnyPropertyFilter
    }
    const groups: unknown = flag.filters.groups
    if (!Array.isArray(groups)) {
        return flag
    }
    return {
        ...flag,
        filters: {
            ...flag.filters,
            // A malformed group keeps its stored shape, so that saving the flag writes it back unchanged.
            groups: groups.map((group) =>
                Array.isArray(group?.properties) ? { ...group, properties: group.properties.map(reannotate) } : group
            ),
        },
    }
}
