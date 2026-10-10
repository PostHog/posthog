import { isPropertyGroupFilterLike } from 'lib/components/PropertyFilters/utils'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'
import type {
    AnyPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    PersonPropertyFilter,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyType,
    SessionPropertyFilter,
} from '~/types'

export type EditableFilter = EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter | GroupPropertyFilter

/** The saved filters of the insight, or of one event, where they are a plain list. */
export type SavedFilters = AnyPropertyFilter[] | PropertyGroupFilter | null | undefined

export interface EditableFilterRow {
    id: string
    kind: 'filter'
    filter: EditableFilter
    /** Set when the property comes from the picker, before its definition loads. */
    propertyType?: PropertyType
    label?: string
}

/** A saved filter, or a group nested inside a group, that the editor keeps but cannot change. */
export interface LockedFilterRow {
    id: string
    kind: 'lockedFilter'
    value: AnyPropertyFilter | PropertyGroupFilterValue
}

export type FilterEditorRow = EditableFilterRow | LockedFilterRow

export interface FilterGroupDraft {
    id: string
    matchMode: FilterLogicalOperator
    rows: FilterEditorRow[]
}

export interface FiltersDraft {
    /** Never empty, so there is always a group to add a filter to. */
    groups: FilterGroupDraft[]
    /** Joins the groups. */
    groupsMatchMode: FilterLogicalOperator
}

const EDITABLE_TYPES: (PropertyFilterType | undefined)[] = [
    PropertyFilterType.Event,
    PropertyFilterType.Person,
    PropertyFilterType.Session,
    PropertyFilterType.Group,
]

const UNSUPPORTED_OPERATORS: PropertyOperator[] = [
    PropertyOperator.In,
    PropertyOperator.NotIn,
    PropertyOperator.Between,
    PropertyOperator.NotBetween,
    PropertyOperator.FlagEvaluatesTo,
]

export function isEditableFilter(value: AnyPropertyFilter | PropertyGroupFilterValue): value is EditableFilter {
    return (
        !isPropertyGroupFilterLike(value) &&
        EDITABLE_TYPES.includes(value.type) &&
        typeof value.key === 'string' &&
        'operator' in value &&
        !!value.operator &&
        !UNSUPPORTED_OPERATORS.includes(value.operator)
    )
}

export function emptyFilterGroup(id: string): FilterGroupDraft {
    return { id, matchMode: FilterLogicalOperator.And, rows: [] }
}

export function parseFilterRows(properties: SavedFilters): FiltersDraft {
    const savedGroups: PropertyGroupFilterValue[] = !properties
        ? []
        : Array.isArray(properties)
          ? [{ type: FilterLogicalOperator.And, values: properties }]
          : properties.values
    const groups = savedGroups
        .filter((group) => group.values.length > 0)
        .map(
            (group, groupIndex): FilterGroupDraft => ({
                id: `group-${groupIndex}`,
                matchMode: group.type,
                rows: group.values.map((value, index) =>
                    isEditableFilter(value)
                        ? { id: `saved-${groupIndex}-${index}`, kind: 'filter', filter: value }
                        : { id: `saved-${groupIndex}-${index}`, kind: 'lockedFilter', value }
                ),
            })
        )

    return {
        groups: groups.length > 0 ? groups : [emptyFilterGroup('group-0')],
        groupsMatchMode: properties && !Array.isArray(properties) ? properties.type : FilterLogicalOperator.And,
    }
}
