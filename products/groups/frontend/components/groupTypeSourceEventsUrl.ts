import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { ActivityTab, GroupType, PropertyFilterType, PropertyOperator } from '~/types'

// Group types are never created in the UI: ingestion registers one when a $groupidentify event first
// references it. These events explain where a type came from and what keeps its groups updated.
function sourceEventsQuery(groupType: GroupType): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        full: true,
        source: {
            kind: NodeKind.EventsQuery,
            select: [...defaultDataTableColumns(NodeKind.EventsQuery), 'properties.$lib'],
            orderBy: ['timestamp DESC'],
            after: '-30d',
            event: '$groupidentify',
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$group_type',
                    operator: PropertyOperator.Exact,
                    value: [groupType.group_type],
                },
            ],
        },
        propertiesViaUrl: true,
    }
}

export function groupTypeSourceEventsUrl(groupType: GroupType): string {
    return combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: sourceEventsQuery(groupType) }).url
}
