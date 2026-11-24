import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

export type ConditionFilterGroup = { type: FilterLogicalOperator; values: AnyPropertyFilter[] }

/** A branch condition as the editor shows it and the API stores a grouped one: groups of filters joined by AND or OR. */
export type ConditionFilterGroups = { type: FilterLogicalOperator; values: ConditionFilterGroup[] }

export function isConditionFilterGroups(value: unknown): value is ConditionFilterGroups {
    return (
        typeof value === 'object' &&
        value !== null &&
        Array.isArray((value as ConditionFilterGroups).values) &&
        Object.values(FilterLogicalOperator).includes((value as ConditionFilterGroups).type)
    )
}

/** Reads a condition's stored `filters.properties`. A flat list, or no filters, is one AND group. */
export function toConditionFilterGroups(
    properties: AnyPropertyFilter[] | ConditionFilterGroups | null | undefined
): ConditionFilterGroups {
    if (isConditionFilterGroups(properties)) {
        return properties
    }
    return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values: properties ?? [] }] }
}

/** One AND group is stored as a flat list, the shape every condition had before groups existed. */
export function fromConditionFilterGroups(groups: ConditionFilterGroups): AnyPropertyFilter[] | ConditionFilterGroups {
    if (groups.values.length === 1 && groups.values[0].type === FilterLogicalOperator.And) {
        return groups.values[0].values
    }
    return groups
}
