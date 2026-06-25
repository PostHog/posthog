import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { buildOwnerFilters } from './codeownersImport'

export function exceptionsUrl(patterns: string[], dateRange: string): string {
    const filters = buildOwnerFilters(patterns)
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
                    event: '$exception',
                    after: dateRange,
                    properties: filters.values,
                    tags: { productKey: ProductKey.ERROR_TRACKING },
                },
                propertiesViaUrl: true,
                showPersistentColumnConfigurator: true,
            },
        }
    ).url
}

export function issuesUrl(patterns: string[], dateRange: string): string {
    return urls.errorTracking({
        filterGroup: buildOwnerFilters(patterns),
        dateRange: { date_from: dateRange, date_to: null },
    })
}
