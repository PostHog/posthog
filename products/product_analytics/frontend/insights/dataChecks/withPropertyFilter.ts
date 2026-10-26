import { isPropertyGroup } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter, FilterLogicalOperator, PropertyGroupFilter } from '~/types'

// Returns null when the filter would need a third level of groups, which the filter editor cannot show.
export function withPropertyFilter(
    properties: AnyPropertyFilter[] | PropertyGroupFilter | undefined,
    filter: AnyPropertyFilter
): AnyPropertyFilter[] | PropertyGroupFilter | null {
    if (!isPropertyGroup(properties)) {
        return [...(properties ?? []), filter]
    }
    if (properties.type === FilterLogicalOperator.And || properties.values.length === 0) {
        return {
            type: FilterLogicalOperator.And,
            values: [...properties.values, { type: FilterLogicalOperator.And, values: [filter] }],
        }
    }
    // (A or B) and filter is (A and filter) or (B and filter), so the filter goes into each AND group.
    if (properties.values.every((group) => group.type === FilterLogicalOperator.And)) {
        return {
            ...properties,
            values: properties.values.map((group) => ({ ...group, values: [...group.values, filter] })),
        }
    }
    return null
}
