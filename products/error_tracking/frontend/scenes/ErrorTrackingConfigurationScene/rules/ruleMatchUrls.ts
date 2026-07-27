import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

export function matchingIssuesUrl(
    properties: AnyPropertyFilter[],
    filterType: FilterLogicalOperator,
    dateRange: string
): string {
    return urls.errorTracking({
        filterGroup: { type: filterType, values: [{ type: filterType, values: properties }] },
        dateRange: { date_from: dateRange, date_to: null },
    })
}

export function matchingExceptionsUrl(properties: AnyPropertyFilter[], dateRange: string): string {
    return combineUrl(
        urls.activity(ActivityTab.ExploreEvents),
        {},
        {
            q: {
                kind: NodeKind.DataTableNode,
                full: true,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                    orderBy: ['timestamp DESC'],
                    after: dateRange,
                    event: '$exception',
                    properties,
                    tags: { productKey: ProductKey.ERROR_TRACKING },
                },
                propertiesViaUrl: true,
                showPersistentColumnConfigurator: true,
            },
        }
    ).url
}
