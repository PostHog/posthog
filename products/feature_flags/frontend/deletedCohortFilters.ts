import { isCohortPropertyFilter } from 'lib/components/PropertyFilters/utils'

import { CohortPropertyFilter, FeatureFlagConfig } from '~/types'

import { isV1FeatureFlagConfig } from './featureFlagConfigFormat'

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
