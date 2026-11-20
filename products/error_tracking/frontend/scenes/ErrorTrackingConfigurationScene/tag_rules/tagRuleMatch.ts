import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab, AnyPropertyFilter, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

// A rule reads only the first exception of a new issue, so the preview counts the first exception of each issue first
// seen in the window. An issue is as old as its oldest fingerprint, because a merge keeps each fingerprint's own
// first_seen. dateRange is one of '-7d', '-30d' and '-90d'.
export function firstExceptionOfNewIssue(dateRange: string): string {
    const since = `now() - INTERVAL ${Number(dateRange.slice(1, -1))} DAY`
    const newIssues = `SELECT issue_id FROM posthog.error_tracking_fingerprint_issue_state GROUP BY issue_id HAVING min(first_seen) >= ${since}`
    return `uuid IN (SELECT argMin(uuid, timestamp) FROM events WHERE event = '$exception' AND timestamp >= ${since} AND issue_id IN (${newIssues}) GROUP BY issue_id)`
}

// The issue list cannot filter on an issue's first exception, so the preview links only to the exceptions it counted.
export function firstExceptionsOfNewIssuesUrl(filters: UniversalFiltersGroup, dateRange: string): string {
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
                    fixedProperties: [
                        {
                            type: filters.type ?? FilterLogicalOperator.And,
                            values: (filters.values as AnyPropertyFilter[]) ?? [],
                        },
                    ],
                    where: [firstExceptionOfNewIssue(dateRange)],
                    tags: { productKey: ProductKey.ERROR_TRACKING },
                },
                showPersistentColumnConfigurator: true,
            },
        }
    ).url
}
