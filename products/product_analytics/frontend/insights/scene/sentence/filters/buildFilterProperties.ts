import { isPropertyGroupFilterLike } from 'lib/components/PropertyFilters/utils'

import type { AnyPropertyFilter, PropertyGroupFilter, PropertyGroupFilterValue } from '~/types'

import { filterValueKind } from './filterOperatorOptions'
import type { FiltersTarget } from './filtersTarget'
import type { EditableFilter, FilterGroupDraft, FiltersDraft } from './parseFilterRows'

export function isFilterComplete(filter: EditableFilter): boolean {
    const { operator, value } = filter
    if (filterValueKind(operator, value) === 'none') {
        return true
    }
    if (Array.isArray(value)) {
        return value.length > 0
    }
    if (typeof value === 'string') {
        return value.trim() !== ''
    }
    return value !== null && value !== undefined
}

// A filter with no value yet is held back, so it cannot break the chart while it is being made.
function groupValues(group: FilterGroupDraft): PropertyGroupFilterValue['values'] {
    const values: PropertyGroupFilterValue['values'] = []
    for (const row of group.rows) {
        if (row.kind === 'lockedFilter') {
            values.push(row.value)
        } else if (isFilterComplete(row.filter)) {
            values.push(row.filter)
        }
    }
    return values
}

export function buildFilterProperties(draft: FiltersDraft): PropertyGroupFilter | undefined {
    const groups = draft.groups
        .map((group): PropertyGroupFilterValue => ({ type: group.matchMode, values: groupValues(group) }))
        // An empty group saved on the insight shows up as a blank group when dashboard filters merge with it.
        .filter((group) => group.values.length > 0)
    return groups.length > 0 ? { type: draft.groupsMatchMode, values: groups } : undefined
}

/** The filters of one event are a plain list, and every one of them must match. */
export function buildSeriesFilterProperties(draft: FiltersDraft): AnyPropertyFilter[] | undefined {
    const filters = draft.groups
        .flatMap(groupValues)
        .filter((value): value is AnyPropertyFilter => !isPropertyGroupFilterLike(value))
    return filters.length > 0 ? filters : undefined
}

export function buildTargetFilters(
    target: FiltersTarget,
    draft: FiltersDraft
): PropertyGroupFilter | AnyPropertyFilter[] | undefined {
    return target.kind === 'series' ? buildSeriesFilterProperties(draft) : buildFilterProperties(draft)
}
