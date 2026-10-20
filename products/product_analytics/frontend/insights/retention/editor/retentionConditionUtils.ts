import { DataWarehousePopoverField, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { EntityTypes, FilterType } from '~/types'

export const MAX_RANGE = 1000

export const retentionDataWarehousePopoverFields: DataWarehousePopoverField[] = [
    { key: 'timestamp_field', label: 'Timestamp', allowHogQL: true },
    { key: 'aggregation_target_field', label: 'Aggregation target', allowHogQL: true },
]

export const actionsTaxonomicGroupTypes = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.Actions,
    TaxonomicFilterGroupType.DataWarehouse,
]

export function retentionEntityToFilter(entity: Record<string, any> | undefined): FilterType {
    if (!entity) {
        return {}
    }

    if (entity.type === EntityTypes.ACTIONS) {
        return { actions: [entity] }
    }
    if (entity.type === EntityTypes.DATA_WAREHOUSE) {
        return { data_warehouse: [entity] }
    }
    return { events: [entity] }
}

export function filterToRetentionEntity(newFilters: FilterType): Record<string, any> | undefined {
    if (newFilters.events && newFilters.events.length > 0) {
        return newFilters.events[0]
    }
    if (newFilters.actions && newFilters.actions.length > 0) {
        return newFilters.actions[0]
    }
    if (newFilters.data_warehouse && newFilters.data_warehouse.length > 0) {
        return newFilters.data_warehouse[0]
    }
    return undefined
}

/** The return range a custom bracket covers, such as "day 2-4", or empty when the bracket has no length. */
export function getRetentionBracketLabel(
    brackets: (number | string | undefined)[],
    index: number,
    unit: string
): string {
    const numericBrackets = brackets.map((bracket) => {
        const parsed = typeof bracket === 'string' ? parseInt(bracket, 10) : (bracket ?? 0)
        return isNaN(parsed) ? 0 : parsed
    })
    const start = 1 + numericBrackets.slice(0, index).reduce((total, length) => total + (length || 0), 0)
    const length = numericBrackets[index] || 0
    if (length <= 0) {
        return ''
    }
    const end = start + length - 1
    return start === end ? `${unit} ${start}` : `${unit} ${start}-${end}`
}
