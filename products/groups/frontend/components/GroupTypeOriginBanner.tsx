import { combineUrl } from 'kea-router'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { ActivityTab, GroupType, PropertyFilterType, PropertyOperator } from '~/types'

// Group types are never created in the UI: ingestion registers one when a $groupidentify event first
// references it. These are the events that explain where a type came from and what keeps it updated.
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

interface GroupTypeOriginBannerProps {
    groupType: GroupType
}

export function GroupTypeOriginBanner({ groupType }: GroupTypeOriginBannerProps): JSX.Element {
    return (
        <LemonBanner
            type="info"
            dismissKey={`group-type-origin-${groupType.group_type_index}-${groupType.group_type}`}
            action={{
                children: 'View source events',
                to: combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: sourceEventsQuery(groupType) }).url,
                'data-attr': 'group-type-origin-view-source-events',
            }}
        >
            PostHog created this group type automatically when an event first referenced "{groupType.group_type}". The
            source events show what sends them.{' '}
            <Link to="https://posthog.com/docs/product-analytics/group-analytics#how-to-create-groups">
                Learn how groups are created
            </Link>
        </LemonBanner>
    )
}
