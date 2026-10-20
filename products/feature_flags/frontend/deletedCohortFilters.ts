import { isCohortPropertyFilter } from 'lib/components/PropertyFilters/utils'

import { CohortPropertyFilter, FeatureFlagConfig } from '~/types'

import { isV1FeatureFlagConfig } from './featureFlagConfigFormat'

/** Whether a condition's deleted cohort still exists, so that its page can restore it. */
export function cohortCanBeRestored(property: CohortPropertyFilter): boolean {
    return !property.cohort_missing
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
        : 'A release condition targets a deleted cohort. Update the release conditions first.'
}

/** The release conditions that target a deleted or missing cohort, one per cohort. */
export function deletedCohortFilters(filters: FeatureFlagConfig | null | undefined): CohortPropertyFilter[] {
    if (!filters || !isV1FeatureFlagConfig(filters)) {
        return []
    }
    // Stored cohort values can be numbers or numeric strings. `5` and `"5"` name the same cohort.
    const byCohort = new Map<string, CohortPropertyFilter>()
    for (const group of filters.groups ?? []) {
        for (const property of group.properties ?? []) {
            const key = String(property.value)
            if (isCohortPropertyFilter(property) && property.cohort_deleted && !byCohort.has(key)) {
                byCohort.set(key, property)
            }
        }
    }
    return [...byCohort.values()]
}
