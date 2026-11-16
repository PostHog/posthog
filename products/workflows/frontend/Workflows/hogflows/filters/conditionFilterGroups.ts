import { AnyPropertyFilter, FilterLogicalOperator, PropertyGroupFilter } from '~/types'

export type ConditionFilterGroup = { type: FilterLogicalOperator; values: AnyPropertyFilter[] }

/** A branch condition as the editor shows it: groups of filters joined by one outer AND or OR. */
export type ConditionFilterGroups = { type: FilterLogicalOperator; values: ConditionFilterGroup[] }

export function isPropertyGroup(value: unknown): value is PropertyGroupFilter {
    return (
        typeof value === 'object' &&
        value !== null &&
        Array.isArray((value as PropertyGroupFilter).values) &&
        Object.values(FilterLogicalOperator).includes((value as PropertyGroupFilter).type)
    )
}

/**
 * Reads a condition's stored `filters.properties`. A flat list is one AND group. Returns null when groups
 * nest deeper than the editor shows, because saving from the editor would then drop the inner groups.
 */
export function toConditionFilterGroups(properties: unknown): ConditionFilterGroups | null {
    if (properties == null || Array.isArray(properties)) {
        return {
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: (properties as AnyPropertyFilter[] | null) ?? [] }],
        }
    }
    if (!isPropertyGroup(properties)) {
        return null
    }
    const groups: ConditionFilterGroup[] = []
    for (const value of properties.values) {
        if (!isPropertyGroup(value)) {
            groups.push({ type: FilterLogicalOperator.And, values: [value as AnyPropertyFilter] })
        } else if (value.values.some(isPropertyGroup)) {
            return null
        } else {
            groups.push({ type: value.type, values: value.values as AnyPropertyFilter[] })
        }
    }
    return { type: properties.type, values: groups }
}

/** One AND group is stored as a flat list, the shape every condition had before groups existed. */
export function fromConditionFilterGroups(groups: ConditionFilterGroups): AnyPropertyFilter[] | PropertyGroupFilter {
    if (groups.values.length === 1 && groups.values[0].type === FilterLogicalOperator.And) {
        return groups.values[0].values
    }
    return groups
}
