import {
    formatPropertyLabel,
    isPropertyGroupFilterLike,
    propertyGroupSummary,
} from 'lib/components/PropertyFilters/utils'

import type { AnyPropertyFilter, CohortType, PropertyGroupFilterValue } from '~/types'

export function describeLockedFilter(
    value: AnyPropertyFilter | PropertyGroupFilterValue,
    cohortsById: Partial<Record<CohortType['id'], CohortType>>
): string {
    const description = isPropertyGroupFilterLike(value)
        ? `(${propertyGroupSummary(value, cohortsById)})`
        : formatPropertyLabel(value, cohortsById).trim()
    return description && description !== '()' ? description : 'A filter this editor cannot show'
}
