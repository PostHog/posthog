import { hogQLToFilterValue } from 'scenes/insights/filters/aggregationTarget'

import { FunnelsQuery, LifecycleQuery, RetentionQuery } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isLifecycleQuery, isRetentionQuery } from '~/queries/utils'

export const CUSTOM_DATA_WAREHOUSE_ITEMS = '__custom_data_warehouse_items__'

export function getCustomAggregationEditorValue(value: string, baseValues: string[]): string {
    return !value || baseValues.includes(value) || value === CUSTOM_DATA_WAREHOUSE_ITEMS ? '' : value
}

/** The query source update that aggregates the insight by `value` (a group, a SQL expression, or custom entities). */
export function aggregationQuerySourceUpdate(
    querySource: FunnelsQuery | LifecycleQuery | RetentionQuery | Record<string, any>,
    value: string
): Partial<FunnelsQuery | LifecycleQuery | RetentionQuery> {
    const { aggregationQuery, groupIndex } = hogQLToFilterValue(value)
    const isCustomEntities = value === CUSTOM_DATA_WAREHOUSE_ITEMS
    if (isFunnelsQuery(querySource)) {
        return {
            aggregation_group_type_index: isCustomEntities ? undefined : groupIndex,
            funnelsFilter: {
                ...querySource.funnelsFilter,
                funnelAggregateByHogQL: isCustomEntities ? undefined : aggregationQuery,
                customAggregationTarget: isCustomEntities ? true : undefined,
            },
        } as FunnelsQuery
    }
    if (isLifecycleQuery(querySource)) {
        return {
            aggregation_group_type_index: isCustomEntities ? undefined : groupIndex,
            customAggregationTarget: isCustomEntities ? true : undefined,
        } as LifecycleQuery
    }
    if (isRetentionQuery(querySource)) {
        return {
            aggregation_group_type_index: isCustomEntities ? undefined : groupIndex,
            retentionFilter: {
                ...querySource.retentionFilter,
                customAggregationTarget: isCustomEntities ? true : undefined,
            },
        } as RetentionQuery
    }
    return { aggregation_group_type_index: groupIndex } as FunnelsQuery
}
